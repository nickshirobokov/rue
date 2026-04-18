"""Generic resource state snapshot helpers."""

from __future__ import annotations

import asyncio
import importlib
import io
import socket
import threading
import types
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import cloudpickle  # type: ignore[import-untyped]
import msgspec


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
_CONTEXTVAR_UNSET = msgspec.UNSET
_ATTR_PLAN_CACHE: dict[type[Any], _AttrPlan] = {}
_CLASS_REF_CACHE: dict[type[Any], tuple[str, str, bytes | None]] = {}
_CLASS_CACHE: dict[tuple[str, str], type[Any]] = {}
_LOCAL_CLASS_CACHE: dict[bytes, type[Any]] = {}


class _AttrPlan(msgspec.Struct, frozen=True):
    slot_names: tuple[str, ...] = ()
    dataclass_field_names: tuple[str, ...] = ()


def _attr_plan(cls: type[Any]) -> _AttrPlan:
    cached = _ATTR_PLAN_CACHE.get(cls)
    if cached is not None:
        return cached

    seen: set[str] = set()
    slot_names: list[str] = []
    for current in cls.__mro__:
        slots = current.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for slot in slots:
            if slot in {"__dict__", "__weakref__"} or slot in seen:
                continue
            seen.add(slot)
            slot_names.append(slot)

    plan = _AttrPlan(
        slot_names=tuple(slot_names),
        dataclass_field_names=tuple(getattr(cls, "__dataclass_fields__", ())),
    )
    _ATTR_PLAN_CACHE[cls] = plan
    return plan


def _class_ref(cls: type[Any]) -> tuple[str, str, bytes | None]:
    cached = _CLASS_REF_CACHE.get(cls)
    if cached is not None:
        return cached

    qualname = cls.__qualname__
    ref = (
        cls.__module__,
        qualname,
        cloudpickle.dumps(cls) if "<locals>" in qualname else None,
    )
    _CLASS_REF_CACHE[cls] = ref
    return ref


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
        value: Any = _CONTEXTVAR_UNSET,
    ) -> None:
        self.name = name
        self._default = default
        self._value = value

    def get(self, default: Any = None) -> Any:
        if self._value is not _CONTEXTVAR_UNSET:
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
        self._live_object_ids: dict[int, int] = {}
        self._live_path_ids: dict[str, int] = {}

    def export_roots(
        self,
        roots: dict[str, Any],
    ) -> tuple[dict[str, int], dict[int, dict[str, Any]], dict[str, list[str]]]:
        root_ids = {
            root_key: self._export_value(value, path=root_key)
            for root_key, value in roots.items()
        }
        self.object_ids = self._live_object_ids
        self.path_ids = self._live_path_ids
        return root_ids, self.nodes, self.ignored_paths

    def _export_value(self, value: Any, *, path: str) -> int:
        if self._is_trackable(value):
            object_id = id(value)
            existing = self.object_ids.get(object_id)
            if existing is not None:
                if existing in self.nodes:
                    return existing
                node_id = existing
            else:
                node_id = self._next_node_id()
                self.object_ids[object_id] = node_id
            self._live_object_ids[object_id] = node_id
        else:
            existing = self.path_ids.get(path)
            if existing is not None and existing not in self.nodes:
                node_id = existing
            elif existing is not None:
                return existing
            else:
                node_id = self._next_node_id()
                self.path_ids[path] = node_id
            self._live_path_ids[path] = node_id

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
            self.nodes[node_id] = self._export_atomic(value)
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
            **self._class_ref_fields(type(value)),
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
                "data": cloudpickle.dumps(value),
            }
        except Exception:
            return {
                "kind": "opaque",
                "module": type(value).__module__,
                "qualname": type(value).__qualname__,
                "display": repr(value),
            }

    @staticmethod
    def _class_ref_fields(cls: type[Any]) -> dict[str, Any]:
        module, qualname, class_data = _class_ref(cls)
        return {
            "module": module,
            "qualname": qualname,
            "class_data": class_data,
        }

    def _export_atomic(self, value: Any) -> dict[str, Any]:
        if isinstance(value, Enum):
            return {
                "kind": "enum",
                **self._class_ref_fields(type(value)),
                "member": value.name,
            }

        if isinstance(value, Path):
            return {
                "kind": "path",
                **self._class_ref_fields(type(value)),
                "value": str(value),
            }

        if isinstance(value, UUID):
            return {"kind": "uuid", "value": msgspec.to_builtins(value)}

        if isinstance(value, datetime):
            return {"kind": "datetime", "value": msgspec.to_builtins(value)}

        if isinstance(value, date):
            return {"kind": "date", "value": msgspec.to_builtins(value)}

        if isinstance(value, time):
            return {"kind": "time", "value": msgspec.to_builtins(value)}

        if isinstance(value, timedelta):
            return {
                "kind": "timedelta",
                "value": msgspec.to_builtins(value),
            }

        return {
            "kind": "pickle",
            "data": cloudpickle.dumps(value),
        }

    @staticmethod
    def _is_primitive(value: Any) -> bool:
        return value is None or isinstance(
            value, (bool, int, float, str, bytes)
        )

    @staticmethod
    def _is_trackable(value: Any) -> bool:
        return not (
            SnapshotExporter._is_primitive(value)
            or isinstance(value, _ATOMIC_VALUE_TYPES)
        )

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
        plan = _attr_plan(type(value))

        if hasattr(value, "__dict__"):
            attrs.update(vars(value))

        for slot in plan.slot_names:
            if slot in attrs:
                continue
            try:
                attrs[slot] = object.__getattribute__(value, slot)
            except AttributeError:
                continue

        for field_name in plan.dataclass_field_names:
            if field_name in attrs:
                continue
            try:
                attrs[field_name] = object.__getattribute__(value, field_name)
            except AttributeError:
                continue

        return list(attrs.items())

    @staticmethod
    def _normalized_name(name: str) -> str:
        return name.lstrip("_").lower()

    @staticmethod
    def _should_ignore_attr(name: str, value: Any) -> bool:
        normalized = SnapshotExporter._normalized_name(name)
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
            return cloudpickle.loads(node["data"])

        if kind == "uuid":
            return msgspec.convert(node["value"], UUID)

        if kind == "date":
            return msgspec.convert(node["value"], date)

        if kind == "datetime":
            return msgspec.convert(node["value"], datetime)

        if kind == "time":
            return msgspec.convert(node["value"], time)

        if kind == "timedelta":
            return msgspec.convert(node["value"], timedelta)

        if kind == "path":
            return self._resolve_class(node)(node["value"])

        if kind == "enum":
            enum_cls = cast("type[Enum]", self._resolve_class(node))
            return getattr(enum_cls, node["member"])

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
            current_var = (
                current
                if isinstance(current, (ContextVar, SnapshotContextVar))
                else None
            )
            current_value = (
                current_var.get(None) if current_var is not None else None
            )
            context_var = SnapshotContextVar(
                node["name"],
                value=current_value,
            )
            self.built[node_id] = context_var
            self.object_ids[id(context_var)] = node_id
            context_var.set(
                self._apply_node(node["value"], context_var.get(None))
            )
            return context_var

        if kind == "list":
            list_value = current if isinstance(current, list) else []
            current_items = list(list_value)
            self.built[node_id] = list_value
            self.object_ids[id(list_value)] = node_id
            list_value[:] = [
                self._apply_node(
                    item_id,
                    current_items[index]
                    if index < len(current_items)
                    else None,
                )
                for index, item_id in enumerate(node["items"])
            ]
            return list_value

        if kind == "tuple":
            tuple_value = tuple(
                self._apply_node(item_id, None) for item_id in node["items"]
            )
            self.built[node_id] = tuple_value
            return tuple_value

        if kind == "set":
            set_value = current if isinstance(current, set) else set()
            self.built[node_id] = set_value
            self.object_ids[id(set_value)] = node_id
            set_value.clear()
            set_value.update(
                self._apply_node(item_id, None) for item_id in node["items"]
            )
            return set_value

        if kind == "frozenset":
            frozen_set_value = frozenset(
                self._apply_node(item_id, None) for item_id in node["items"]
            )
            self.built[node_id] = frozen_set_value
            return frozen_set_value

        if kind == "dict":
            dict_value = current if isinstance(current, dict) else {}
            current_entries = dict(dict_value)
            self.built[node_id] = dict_value
            self.object_ids[id(dict_value)] = node_id
            dict_value.clear()
            for key_id, value_id in node["entries"]:
                key = self._apply_node(key_id, None)
                value = self._apply_node(value_id, current_entries.get(key))
                dict_value[key] = value
            return dict_value

        cls = self._resolve_class(node)
        existing_object = current if isinstance(current, cls) else None
        if existing_object is None:
            new_object = cast("Any", cls.__new__)(cls)
            result = cast("Any", new_object)
        else:
            result = existing_object
        existing = existing_object is not None
        self.built[node_id] = result
        self.object_ids[id(result)] = node_id

        tracked_names = (
            {
                name
                for name, value in SnapshotExporter._iter_state_attrs(result)
                if not SnapshotExporter._should_ignore_attr(name, value)
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
            class_data = node["class_data"]
            cached = _LOCAL_CLASS_CACHE.get(class_data)
            if cached is not None:
                return cached
            resolved = cast("type[Any]", cloudpickle.loads(class_data))
            _LOCAL_CLASS_CACHE[class_data] = resolved
            return resolved

        key = (node["module"], node["qualname"])
        cached = _CLASS_CACHE.get(key)
        if cached is not None:
            return cached

        module = importlib.import_module(node["module"])
        current: Any = module
        for part in node["qualname"].split("."):
            if part == "<locals>":
                continue
            current = getattr(current, part)
        resolved = cast("type[Any]", current)
        _CLASS_CACHE[key] = resolved
        return resolved
