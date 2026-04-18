"""Generic resource state snapshot helpers."""

from __future__ import annotations

import asyncio
import importlib
import io
import socket
import threading
import types
from contextvars import ContextVar
from dataclasses import is_dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.resources.serialization import deserialize_value, serialize_value


_LOCK_TYPES = (type(threading.Lock()), type(threading.RLock()))
_RUNTIME_IGNORE_TYPES = (
    asyncio.Future,
    io.IOBase,
    socket.socket,
    types.AsyncGeneratorType,
    types.GeneratorType,
    types.ModuleType,
    *_LOCK_TYPES,
)
_ATOMIC_VALUE_TYPES = (
    UUID,
    Path,
    date,
    datetime,
    time,
    timedelta,
    Enum,
)


class OpaqueSnapshotValue:
    """Best-effort stand-in for non-scannable shadow values."""

    def __init__(
        self,
        *,
        module: str | None,
        qualname: str | None,
        display: str,
    ) -> None:
        self.__module__ = module or type(self).__module__
        self.__qualname__ = qualname or type(self).__qualname__
        self._display = display

    def __repr__(self) -> str:
        return self._display


class SnapshotContextVar:
    """ContextVar-like wrapper whose value persists on the object itself."""

    def __init__(
        self,
        name: str,
        *,
        default: Any = None,
        value: Any = None,
    ) -> None:
        self.name = name
        self._default = default
        self._value = value

    def get(self, default: Any = None) -> Any:
        if self._value is not None:
            return self._value
        if default is not None:
            return default
        return self._default

    def set(self, value: Any) -> Any:
        self._value = value
        return value


class SnapshotExporter:
    """Walk one object graph and emit a diff-friendly pure-data snapshot."""

    def __init__(
        self,
        *,
        known_ids: dict[int, int] | None = None,
        known_paths: dict[str, int] | None = None,
        next_id: int | None = None,
    ) -> None:
        self.object_ids = dict(known_ids or {})
        self.path_ids = dict(known_paths or {})
        self.next_id = next_id or (max(self.object_ids.values(), default=0) + 1)
        self.nodes: dict[int, dict[str, Any]] = {}
        self.ignored_paths: dict[str, list[str]] = {}

    def export_roots(
        self,
        roots: dict[str, Any],
    ) -> tuple[dict[str, int], dict[int, dict[str, Any]], dict[str, list[str]]]:
        root_ids = {
            root_key: self._export_value(value, path=root_key)
            for root_key, value in roots.items()
        }
        return root_ids, self.nodes, self.ignored_paths

    def _export_value(self, value: Any, *, path: str) -> int:
        if self._is_trackable(value):
            existing = self.object_ids.get(id(value))
            if existing is not None:
                if existing in self.nodes:
                    return existing
                node_id = existing
            else:
                node_id = self._next_node_id()
                self.object_ids[id(value)] = node_id
        else:
            existing = self.path_ids.get(path)
            if existing is not None and existing not in self.nodes:
                node_id = existing
            elif existing is not None:
                return existing
            else:
                node_id = self._next_node_id()
                self.path_ids[path] = node_id

        if isinstance(value, (ContextVar, SnapshotContextVar)):
            self.nodes[node_id] = {
                "kind": "contextvar",
                "name": value.name,
                "value": None,
            }
            current = value.get(None)
            self.nodes[node_id]["value"] = self._export_value(
                current,
                path=f"{path}.value",
            )
            return node_id

        if self._is_primitive(value):
            self.nodes[node_id] = {"kind": "value", "value": value}
            return node_id

        if isinstance(value, _ATOMIC_VALUE_TYPES):
            self.nodes[node_id] = {
                "kind": "pickle",
                "data": serialize_value(value),
            }
            return node_id

        if isinstance(value, dict):
            self.nodes[node_id] = {"kind": "dict", "entries": []}
            self.nodes[node_id]["entries"] = [
                [
                    self._export_value(key, path=f"{path}.key[{index}]"),
                    self._export_value(item, path=f"{path}[{index}]"),
                ]
                for index, (key, item) in enumerate(value.items())
            ]
            return node_id

        if isinstance(value, list):
            self.nodes[node_id] = {"kind": "list", "items": []}
            self.nodes[node_id]["items"] = [
                self._export_value(item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
            return node_id

        if isinstance(value, tuple):
            self.nodes[node_id] = {"kind": "tuple", "items": []}
            self.nodes[node_id]["items"] = [
                self._export_value(item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
            return node_id

        if isinstance(value, set):
            self.nodes[node_id] = {"kind": "set", "items": []}
            self.nodes[node_id]["items"] = [
                self._export_value(item, path=f"{path}[{index}]")
                for index, item in enumerate(self._ordered_set_items(value))
            ]
            return node_id

        if isinstance(value, frozenset):
            self.nodes[node_id] = {"kind": "frozenset", "items": []}
            self.nodes[node_id]["items"] = [
                self._export_value(item, path=f"{path}[{index}]")
                for index, item in enumerate(self._ordered_set_items(value))
            ]
            return node_id

        if callable(value):
            self.nodes[node_id] = self._export_pickle_or_opaque(value)
            return node_id

        self.nodes[node_id] = {
            "kind": "object",
            "module": type(value).__module__,
            "qualname": type(value).__qualname__,
            "class_data": (
                serialize_value(type(value))
                if "<locals>" in type(value).__qualname__
                else None
            ),
            "attrs": {},
        }

        attrs: dict[str, int] = {}
        for name, attr_value in self._iter_state_attrs(value):
            if self._should_ignore_attr(name, attr_value):
                self.ignored_paths.setdefault(path, []).append(name)
                continue
            attrs[name] = self._export_value(attr_value, path=f"{path}.{name}")

        if attrs:
            self.nodes[node_id]["attrs"] = attrs
            return node_id

        if type(value).__module__ in {"builtins", "_thread"}:
            self.nodes[node_id] = {
                "kind": "opaque",
                "module": type(value).__module__,
                "qualname": type(value).__qualname__,
                "display": repr(value),
            }
            return node_id

        self.nodes[node_id] = self._export_pickle_or_opaque(value)
        return node_id

    def _export_pickle_or_opaque(self, value: Any) -> dict[str, Any]:
        try:
            return {
                "kind": "pickle",
                "data": serialize_value(value),
            }
        except Exception:
            return {
                "kind": "opaque",
                "module": type(value).__module__,
                "qualname": type(value).__qualname__,
                "display": repr(value),
            }

    @staticmethod
    def _is_primitive(value: Any) -> bool:
        return value is None or isinstance(
            value, (bool, int, float, str, bytes)
        )

    @staticmethod
    def _is_trackable(value: Any) -> bool:
        return not SnapshotExporter._is_primitive(value)

    def _next_node_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    @staticmethod
    def _ordered_set_items(values: set[Any] | frozenset[Any]) -> list[Any]:
        return sorted(
            values,
            key=lambda item: (
                type(item).__module__,
                type(item).__qualname__,
                repr(item),
            ),
        )

    @staticmethod
    def _iter_state_attrs(value: Any) -> list[tuple[str, Any]]:
        attrs: dict[str, Any] = {}

        if hasattr(value, "__dict__"):
            attrs.update(vars(value))

        for cls in type(value).__mro__:
            slots = cls.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for slot in slots:
                if slot in {"__dict__", "__weakref__"}:
                    continue
                if slot in attrs or not hasattr(value, slot):
                    continue
                attrs[slot] = object.__getattribute__(value, slot)

        if is_dataclass(value):
            for field_name in value.__dataclass_fields__:
                if field_name in attrs or not hasattr(value, field_name):
                    continue
                attrs[field_name] = getattr(value, field_name)

        return list(attrs.items())

    @staticmethod
    def _normalized_name(name: str) -> str:
        return name.lstrip("_").lower()

    def _should_ignore_attr(self, name: str, value: Any) -> bool:
        normalized = self._normalized_name(name)
        if normalized in {"cache", "memo"}:
            return True
        if isinstance(value, _RUNTIME_IGNORE_TYPES):
            return True
        if callable(value):
            return True
        return False


class SnapshotApplier:
    """Apply a snapshot graph to existing live objects in place."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        *,
        object_ids: dict[int, int] | None = None,
    ) -> None:
        self.root_ids: dict[str, int] = dict(snapshot["root_ids"])
        self.nodes: dict[int, dict[str, Any]] = {
            int(node_id): node for node_id, node in snapshot["nodes"].items()
        }
        self.object_ids = object_ids if object_ids is not None else {}
        self.built: dict[int, Any] = {}

    def apply_roots(self, roots: dict[str, Any]) -> dict[str, Any]:
        return {
            root_key: self._apply_node(
                self.root_ids[root_key],
                roots.get(root_key),
            )
            for root_key in self.root_ids
        }

    def _apply_node(self, node_id: int, current: Any) -> Any:
        if node_id in self.built:
            return self.built[node_id]

        node = self.nodes[node_id]
        kind = node["kind"]

        if kind == "value":
            return node["value"]

        if kind == "pickle":
            return deserialize_value(node["data"])

        if kind == "opaque":
            if current is not None:
                self.object_ids[id(current)] = node_id
                self.built[node_id] = current
                return current
            result = OpaqueSnapshotValue(
                module=node.get("module"),
                qualname=node.get("qualname"),
                display=node["display"],
            )
            self.built[node_id] = result
            self.object_ids[id(result)] = node_id
            return result

        if kind == "contextvar":
            current_value = (
                current.get(None)
                if isinstance(current, (ContextVar, SnapshotContextVar))
                else None
            )
            result = SnapshotContextVar(
                node["name"],
                value=current_value,
            )
            self.built[node_id] = result
            self.object_ids[id(result)] = node_id
            result.set(self._apply_node(node["value"], result.get(None)))
            return result

        if kind == "list":
            result = current if isinstance(current, list) else []
            current_items = list(result)
            self.built[node_id] = result
            self.object_ids[id(result)] = node_id
            result[:] = [
                self._apply_node(
                    item_id,
                    current_items[index]
                    if index < len(current_items)
                    else None,
                )
                for index, item_id in enumerate(node["items"])
            ]
            return result

        if kind == "tuple":
            result = tuple(
                self._apply_node(item_id, None) for item_id in node["items"]
            )
            self.built[node_id] = result
            return result

        if kind == "set":
            result = current if isinstance(current, set) else set()
            self.built[node_id] = result
            self.object_ids[id(result)] = node_id
            result.clear()
            result.update(
                self._apply_node(item_id, None) for item_id in node["items"]
            )
            return result

        if kind == "frozenset":
            result = frozenset(
                self._apply_node(item_id, None) for item_id in node["items"]
            )
            self.built[node_id] = result
            return result

        if kind == "dict":
            result = current if isinstance(current, dict) else {}
            current_entries = dict(result)
            self.built[node_id] = result
            self.object_ids[id(result)] = node_id
            result.clear()
            for key_id, value_id in node["entries"]:
                key = self._apply_node(key_id, None)
                value = self._apply_node(value_id, current_entries.get(key))
                result[key] = value
            return result

        cls = self._resolve_class(node)
        existing = current is not None and isinstance(current, cls)
        result = current if existing else cls.__new__(cls)
        self.built[node_id] = result
        self.object_ids[id(result)] = node_id

        tracked_names = (
            {
                name
                for name, value in SnapshotExporter._iter_state_attrs(result)
                if not SnapshotExporter()._should_ignore_attr(name, value)
            }
            if existing
            else set()
        )
        target_names = set(node["attrs"])
        for attr_name in tracked_names - target_names:
            delattr(result, attr_name)
        for attr_name, child_id in node["attrs"].items():
            child_current = getattr(result, attr_name, None)
            object.__setattr__(
                result,
                attr_name,
                self._apply_node(child_id, child_current),
            )
        return result

    @staticmethod
    def _resolve_class(node: dict[str, Any]) -> type[Any]:
        if node.get("class_data") is not None:
            return deserialize_value(node["class_data"])

        module = importlib.import_module(node["module"])
        current: Any = module
        for part in node["qualname"].split("."):
            if part == "<locals>":
                continue
            current = getattr(current, part)
        return current
