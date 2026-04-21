"""Generic resource state snapshot helpers."""

from __future__ import annotations

import asyncio
import importlib
import io
import socket
import threading
import types
from collections.abc import Iterable
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import cloudpickle  # type: ignore[import-untyped]
import msgspec
from pycrdt import Array, Doc, Map


type NodeId = str

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
_PATH_TRACKED_KINDS = {
    "value",
    "bigint",
    "uuid",
    "date",
    "datetime",
    "time",
    "timedelta",
    "path",
    "enum",
}
_CONTEXTVAR_UNSET = msgspec.UNSET
_PYCRDT_INT_MIN = -(2**63)
_PYCRDT_INT_MAX = 2**63 - 1
_ATTR_PLAN_CACHE: dict[type[Any], _AttrPlan] = {}
_CLASS_REF_CACHE: dict[type[Any], tuple[str, str, bytes | None]] = {}
_CLASS_CACHE: dict[tuple[str, str], type[Any]] = {}
_LOCAL_CLASS_CACHE: dict[bytes, type[Any]] = {}


def _primitive(value: object) -> object:
    if isinstance(value, bytearray):
        return bytes(value)
    return value


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


def _bytes(value: object) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    msg = f"Expected bytes-compatible value, got {type(value)!r}"
    raise TypeError(msg)


def _required_bytes(value: object) -> bytes:
    data = _bytes(value)
    if data is None:
        msg = "Expected non-null bytes value"
        raise TypeError(msg)
    return data


def _normalized_name(name: str) -> str:
    return name.lstrip("_").lower()


def _should_ignore_attr(name: str, value: object) -> bool:
    normalized = _normalized_name(name)
    if normalized in {"cache", "memo", "session"}:
        return True
    if name.startswith("_") and (
        isinstance(value, ContextVar)
        or type(value).__name__ == "SnapshotContextVar"
    ):
        return True
    if isinstance(value, _RUNTIME_IGNORE_TYPES):
        return True
    return bool(callable(value))


def _iter_state_attrs(value: object) -> list[tuple[str, object]]:
    attrs: dict[str, object] = {}
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


def _local_counter(
    node_id: NodeId,
    actor_id: int,
) -> int | None:
    prefix = f"{actor_id}:"
    if not node_id.startswith(prefix):
        return None
    return int(node_id.removeprefix(prefix))


def _next_local_counter(
    actor_id: int,
    *,
    object_ids: dict[int, NodeId] | None = None,
    path_ids: dict[str, NodeId] | None = None,
    default: int = 1,
) -> int:
    counters = [
        counter
        for node_id in (
            *cast("dict[int, NodeId]", object_ids or {}).values(),
            *cast("dict[str, NodeId]", path_ids or {}).values(),
        )
        if (counter := _local_counter(node_id, actor_id)) is not None
    ]
    return max(counters, default=default - 1) + 1


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
        """Return the stored display text."""
        return self._display


class SnapshotContextVar:
    """ContextVar-like wrapper whose value persists on the object itself."""

    def __init__(
        self,
        name: str,
        *,
        default: object | None = None,
        value: object = _CONTEXTVAR_UNSET,
    ) -> None:
        self.name = name
        self._default = default
        self._value = value

    def get(self, default: object | None = None) -> object | None:
        """Return the current value or the provided default."""
        if self._value is not _CONTEXTVAR_UNSET:
            return self._value
        if default is not None:
            return default
        return self._default

    def set(self, value: object) -> object:
        """Store and return a new value."""
        self._value = value
        return value


class SnapshotExporter:
    """Walk one object graph and emit a diff-friendly pure-data snapshot."""

    def __init__(
        self,
        *,
        actor_id: int,
        known_ids: dict[int, NodeId] | None = None,
        known_paths: dict[str, NodeId] | None = None,
        next_id: int | None = None,
    ) -> None:
        self.actor_id = actor_id
        self.object_ids = dict(known_ids or {})
        self.path_ids = dict(known_paths or {})
        self.next_id = next_id or _next_local_counter(
            actor_id,
            object_ids=self.object_ids,
            path_ids=self.path_ids,
        )
        self.nodes: dict[NodeId, dict[str, Any]] = {}
        self.ignored_paths: dict[str, list[str]] = {}
        self._live_object_ids: dict[int, NodeId] = {}
        self._live_path_ids: dict[str, NodeId] = {}

    def export_roots(
        self,
        roots: dict[str, Any],
    ) -> tuple[
        dict[str, NodeId],
        dict[NodeId, dict[str, Any]],
        dict[str, list[str]],
    ]:
        """Export the provided roots into a snapshot payload."""
        root_ids = {
            root_key: self._export_value(value, path=root_key)
            for root_key, value in roots.items()
        }
        self.object_ids = self._live_object_ids
        self.path_ids = self._live_path_ids
        return root_ids, self.nodes, self.ignored_paths

    def _export_value(  # noqa: C901, PLR0911, PLR0912
        self,
        value: object,
        *,
        path: str,
    ) -> NodeId:
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
                "value": self._export_value(
                    value.get(None),
                    path=f"{path}.value",
                ),
            }
            return node_id

        if (
            self._is_primitive(value)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and (value < _PYCRDT_INT_MIN or value > _PYCRDT_INT_MAX)
        ):
            self.nodes[node_id] = {
                "kind": "bigint",
                "value": str(value),
            }
            return node_id

        if self._is_primitive(value):
            self.nodes[node_id] = {
                "kind": "value",
                "value": value,
            }
            return node_id

        if isinstance(value, _ATOMIC_VALUE_TYPES):
            self.nodes[node_id] = self._export_atomic(value)
            return node_id

        if isinstance(value, dict):
            self.nodes[node_id] = {
                "kind": "dict",
                "entries": [
                    [
                        self._export_value(key, path=f"{path}.key[{index}]"),
                        self._export_value(item, path=f"{path}[{index}]"),
                    ]
                    for index, (key, item) in enumerate(value.items())
                ],
            }
            return node_id

        if isinstance(value, list):
            self.nodes[node_id] = {
                "kind": "list",
                "items": [
                    self._export_value(item, path=f"{path}[{index}]")
                    for index, item in enumerate(value)
                ],
            }
            return node_id

        if isinstance(value, tuple):
            self.nodes[node_id] = {
                "kind": "tuple",
                "items": [
                    self._export_value(item, path=f"{path}[{index}]")
                    for index, item in enumerate(value)
                ],
            }
            return node_id

        if isinstance(value, set):
            self.nodes[node_id] = {
                "kind": "set",
                "items": [
                    self._export_value(item, path=f"{path}[{index}]")
                    for index, item in enumerate(self._ordered_set_items(value))
                ],
            }
            return node_id

        if isinstance(value, frozenset):
            self.nodes[node_id] = {
                "kind": "frozenset",
                "items": [
                    self._export_value(item, path=f"{path}[{index}]")
                    for index, item in enumerate(self._ordered_set_items(value))
                ],
            }
            return node_id

        if callable(value):
            self.nodes[node_id] = self._export_pickle_or_opaque(value)
            return node_id

        self.nodes[node_id] = {
            "kind": "object",
            **self._class_ref_fields(type(value)),
            "attrs": {},
        }

        attrs: dict[str, NodeId] = {}
        for name, attr_value in _iter_state_attrs(value):
            if _should_ignore_attr(name, attr_value):
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

    def _export_pickle_or_opaque(self, value: object) -> dict[str, Any]:
        try:
            return {
                "kind": "pickle",
                "data": cloudpickle.dumps(value),
            }
        except Exception:  # noqa: BLE001
            return {
                "kind": "opaque",
                "module": type(value).__module__,
                "qualname": type(value).__qualname__,
                "display": repr(value),
            }

    @staticmethod
    def _class_ref_fields(resource_cls: type[Any]) -> dict[str, Any]:
        module, qualname, class_data = _class_ref(resource_cls)
        return {
            "module": module,
            "qualname": qualname,
            "class_data": class_data,
        }

    def _export_atomic(  # noqa: PLR0911
        self,
        value: object,
    ) -> dict[str, Any]:
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
            return {"kind": "uuid", "value": str(value)}

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
    def _is_primitive(value: object) -> bool:
        return value is None or isinstance(
            value,
            (bool, int, float, str, bytes),
        )

    @staticmethod
    def _is_trackable(value: object) -> bool:
        return not (
            SnapshotExporter._is_primitive(value)
            or isinstance(value, _ATOMIC_VALUE_TYPES)
        )

    def _next_node_id(self) -> NodeId:
        value = f"{self.actor_id}:{self.next_id}"
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


class SnapshotApplier:
    """Apply a snapshot graph to existing live objects in place."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        *,
        object_ids: dict[int, NodeId] | None = None,
    ) -> None:
        self.root_ids: dict[str, NodeId] = dict(snapshot["root_ids"])
        self.nodes: dict[NodeId, dict[str, Any]] = {
            str(node_id): node for node_id, node in snapshot["nodes"].items()
        }
        self.object_ids = object_ids if object_ids is not None else {}
        self.built: dict[NodeId, Any] = {}

    def apply_roots(self, roots: dict[str, object]) -> dict[str, object]:
        """Apply the snapshot to the provided live roots."""
        return {
            root_key: self._apply_node(
                self.root_ids[root_key],
                roots.get(root_key),
            )
            for root_key in self.root_ids
        }

    def _apply_node(  # noqa: C901, PLR0911, PLR0912, PLR0915
        self,
        node_id: NodeId,
        current: object,
    ) -> object:
        if node_id in self.built:
            return self.built[node_id]

        node = self.nodes[node_id]
        kind = node["kind"]

        if kind == "value":
            return _primitive(node["value"])

        if kind == "pickle":
            return cloudpickle.loads(_required_bytes(node["data"]))

        if kind == "uuid":
            return msgspec.convert(node["value"], UUID)

        if kind == "bigint":
            return int(node["value"])

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
                    (
                        current_items[index]
                        if index < len(current_items)
                        else None
                    ),
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
                for name, value in _iter_state_attrs(result)
                if not _should_ignore_attr(name, value)
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
            class_data = _required_bytes(node["class_data"])
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


class SnapshotDeltaApplier(SnapshotApplier):
    """Apply only changed subtrees between two snapshots."""

    def __init__(
        self,
        before_snapshot: dict[str, Any],
        after_snapshot: dict[str, Any],
        *,
        object_ids: dict[int, NodeId] | None = None,
    ) -> None:
        super().__init__(after_snapshot, object_ids=object_ids)
        self._before_applier = SnapshotApplier(before_snapshot)
        self.before_root_ids: dict[str, NodeId] = dict(
            before_snapshot["root_ids"]
        )
        self.before_nodes: dict[NodeId, dict[str, Any]] = {
            str(node_id): node
            for node_id, node in before_snapshot["nodes"].items()
        }
        self._equal_cache: dict[tuple[NodeId, NodeId], bool] = {}
        self._equal_pending: set[tuple[NodeId, NodeId]] = set()

    def apply_roots(self, roots: dict[str, object]) -> dict[str, object]:
        """Apply only the changed portions of the after snapshot."""
        return {
            root_key: self._patch_node(
                self.before_root_ids.get(root_key),
                self.root_ids[root_key],
                roots.get(root_key),
            )
            for root_key in self.root_ids
        }

    def _patch_node(  # noqa: C901, PLR0912
        self,
        before_id: NodeId | None,
        after_id: NodeId,
        current: object,
    ) -> object:
        if after_id in self.built:
            return self.built[after_id]

        if (
            before_id is not None
            and current is not None
            and self._subtrees_equal(before_id, after_id)
        ):
            return self._reuse_current(after_id, current)

        after_node = self.nodes[after_id]
        kind = after_node["kind"]
        before_node = (
            self.before_nodes.get(before_id) if before_id is not None else None
        )

        if kind == "contextvar":
            current_var = (
                current
                if isinstance(current, (ContextVar, SnapshotContextVar))
                else None
            )
            current_value = (
                current_var.get(None) if current_var is not None else None
            )
            context_var = (
                current_var
                if current_var is not None
                else SnapshotContextVar(
                    after_node["name"],
                    value=current_value,
                )
            )
            self.built[after_id] = context_var
            self.object_ids[id(context_var)] = after_id
            context_var.set(
                self._patch_node(
                    (
                        cast("NodeId", before_node["value"])
                        if before_node is not None
                        and before_node["kind"] == "contextvar"
                        else None
                    ),
                    cast("NodeId", after_node["value"]),
                    current_value,
                )
            )
            return context_var

        if kind == "list":
            list_value = current if isinstance(current, list) else []
            current_items = list(list_value)
            before_items = (
                cast("list[NodeId]", before_node["items"])
                if before_node is not None and before_node["kind"] == "list"
                else []
            )
            self.built[after_id] = list_value
            self.object_ids[id(list_value)] = after_id
            list_value[:] = [
                self._patch_node(
                    before_items[index] if index < len(before_items) else None,
                    item_id,
                    current_items[index] if index < len(current_items) else None,
                )
                for index, item_id in enumerate(
                    cast("list[NodeId]", after_node["items"])
                )
            ]
            return list_value

        if kind == "tuple":
            current_items = current if isinstance(current, tuple) else ()
            before_items = (
                cast("list[NodeId]", before_node["items"])
                if before_node is not None and before_node["kind"] == "tuple"
                else []
            )
            tuple_value = tuple(
                self._patch_node(
                    before_items[index] if index < len(before_items) else None,
                    item_id,
                    current_items[index] if index < len(current_items) else None,
                )
                for index, item_id in enumerate(
                    cast("list[NodeId]", after_node["items"])
                )
            )
            self.built[after_id] = tuple_value
            self.object_ids[id(tuple_value)] = after_id
            return tuple_value

        if kind == "dict":
            dict_value = current if isinstance(current, dict) else {}
            current_entries = dict(dict_value)
            before_entries = (
                list(cast("list[list[NodeId]]", before_node["entries"]))
                if before_node is not None and before_node["kind"] == "dict"
                else []
            )
            after_entries = cast("list[list[NodeId]]", after_node["entries"])
            self.built[after_id] = dict_value
            self.object_ids[id(dict_value)] = after_id

            for before_key_id, _ in before_entries:
                if self._has_matching_key(after_entries, before_key_id):
                    continue
                baseline_key = self._before_applier._apply_node(
                    before_key_id,
                    None,
                )
                current_key = next(
                    (
                        candidate
                        for candidate in current_entries
                        if candidate == baseline_key
                    ),
                    None,
                )
                if current_key is None:
                    continue
                dict_value.pop(current_key, None)
                current_entries.pop(current_key, None)

            for after_key_id, after_value_id in after_entries:
                before_key_id, before_value_id = self._match_dict_entry(
                    before_entries,
                    after_key_id,
                )
                key = self._patch_node(before_key_id, after_key_id, None)
                current_key = next(
                    (
                        candidate
                        for candidate in current_entries
                        if candidate == key
                    ),
                    key,
                )
                value = self._patch_node(
                    before_value_id,
                    after_value_id,
                    current_entries.get(current_key),
                )
                dict_value[current_key] = value
                current_entries[current_key] = value
            return dict_value

        if kind == "object":
            cls = self._resolve_class(after_node)
            result = (
                current if isinstance(current, cls) else cast("Any", cls.__new__)(cls)
            )
            existing = isinstance(current, cls)
            before_attrs = (
                cast("dict[str, NodeId]", before_node["attrs"])
                if before_node is not None
                and before_node["kind"] == "object"
                and self._same_class(before_node, after_node)
                else {}
            )
            self.built[after_id] = result
            self.object_ids[id(result)] = after_id

            if existing:
                target_names = set(cast("dict[str, NodeId]", after_node["attrs"]))
                for attr_name in set(before_attrs) - target_names:
                    if hasattr(result, attr_name):
                        delattr(result, attr_name)

            for attr_name, child_id in cast(
                "dict[str, NodeId]", after_node["attrs"]
            ).items():
                object.__setattr__(
                    result,
                    attr_name,
                    self._patch_node(
                        before_attrs.get(attr_name),
                        child_id,
                        getattr(result, attr_name, None),
                    ),
                )
            return result

        return super()._apply_node(after_id, current)

    def _reuse_current(self, after_id: NodeId, current: object) -> object:
        if SnapshotExporter._is_trackable(current):
            self.built[after_id] = current
            self.object_ids[id(current)] = after_id
        return current

    def _match_dict_entry(
        self,
        before_entries: list[list[NodeId]],
        after_key_id: NodeId,
    ) -> tuple[NodeId | None, NodeId | None]:
        for before_key_id, before_value_id in before_entries:
            if self._subtrees_equal(before_key_id, after_key_id):
                return before_key_id, before_value_id
        return None, None

    def _has_matching_key(
        self,
        entries: list[list[NodeId]],
        key_id: NodeId,
    ) -> bool:
        return any(
            self._subtrees_equal(key_id, entry_key_id)
            for entry_key_id, _ in entries
        )

    def _subtrees_equal(self, before_id: NodeId, after_id: NodeId) -> bool:
        cached = self._equal_cache.get((before_id, after_id))
        if cached is not None:
            return cached

        marker = (before_id, after_id)
        if marker in self._equal_pending:
            return True
        self._equal_pending.add(marker)
        try:
            before_node = self.before_nodes.get(before_id)
            after_node = self.nodes.get(after_id)
            if before_node is None or after_node is None:
                result = before_node == after_node
            elif before_node["kind"] != after_node["kind"]:
                result = False
            else:
                kind = before_node["kind"]
                match kind:
                    case "value" | "bigint" | "uuid":
                        result = before_node["value"] == after_node["value"]
                    case "pickle":
                        result = before_node["data"] == after_node["data"]
                    case "date" | "datetime" | "time" | "timedelta":
                        result = before_node["value"] == after_node["value"]
                    case "path":
                        result = (
                            self._same_class(before_node, after_node)
                            and before_node["value"] == after_node["value"]
                        )
                    case "enum":
                        result = (
                            self._same_class(before_node, after_node)
                            and before_node["member"] == after_node["member"]
                        )
                    case "opaque":
                        result = (
                            before_node.get("module") == after_node.get("module")
                            and before_node.get("qualname")
                            == after_node.get("qualname")
                            and before_node["display"] == after_node["display"]
                        )
                    case "contextvar":
                        result = before_node["name"] == after_node["name"] and self._subtrees_equal(
                            cast("NodeId", before_node["value"]),
                            cast("NodeId", after_node["value"]),
                        )
                    case "list" | "tuple":
                        before_items = cast("list[NodeId]", before_node["items"])
                        after_items = cast("list[NodeId]", after_node["items"])
                        result = len(before_items) == len(after_items) and all(
                            self._subtrees_equal(left_id, right_id)
                            for left_id, right_id in zip(
                                before_items,
                                after_items,
                                strict=False,
                            )
                        )
                    case "set" | "frozenset":
                        before_items = list(
                            cast("list[NodeId]", before_node["items"])
                        )
                        after_items = cast("list[NodeId]", after_node["items"])
                        result = len(before_items) == len(after_items)
                        for after_item_id in after_items:
                            matched = next(
                                (
                                    index
                                    for index, before_item_id in enumerate(
                                        before_items
                                    )
                                    if self._subtrees_equal(
                                        before_item_id,
                                        after_item_id,
                                    )
                                ),
                                None,
                            )
                            if matched is None:
                                result = False
                                break
                            before_items.pop(matched)
                    case "dict":
                        before_entries = list(
                            cast("list[list[NodeId]]", before_node["entries"])
                        )
                        after_entries = cast(
                            "list[list[NodeId]]", after_node["entries"]
                        )
                        result = len(before_entries) == len(after_entries)
                        for after_key_id, after_value_id in after_entries:
                            matched = next(
                                (
                                    index
                                    for index, (before_key_id, _) in enumerate(
                                        before_entries
                                    )
                                    if self._subtrees_equal(
                                        before_key_id,
                                        after_key_id,
                                    )
                                ),
                                None,
                            )
                            if matched is None:
                                result = False
                                break
                            _, before_value_id = before_entries.pop(matched)
                            if not self._subtrees_equal(
                                before_value_id,
                                after_value_id,
                            ):
                                result = False
                                break
                    case "object":
                        before_attrs = cast("dict[str, NodeId]", before_node["attrs"])
                        after_attrs = cast("dict[str, NodeId]", after_node["attrs"])
                        result = (
                            self._same_class(before_node, after_node)
                            and set(before_attrs) == set(after_attrs)
                            and all(
                                self._subtrees_equal(
                                    before_attrs[attr_name],
                                    after_attrs[attr_name],
                                )
                                for attr_name in after_attrs
                            )
                        )
                    case _:
                        result = False
        finally:
            self._equal_pending.discard(marker)

        self._equal_cache[(before_id, after_id)] = result
        return result

    @staticmethod
    def _same_class(
        before_node: dict[str, Any],
        after_node: dict[str, Any],
    ) -> bool:
        return (
            before_node.get("module") == after_node.get("module")
            and before_node.get("qualname") == after_node.get("qualname")
            and before_node.get("class_data") == after_node.get("class_data")
        )


def build_path_ids(  # noqa: C901
    payload: dict[str, Any],
) -> dict[str, NodeId]:
    """Reconstruct path-based node IDs for non-trackable leaf values."""
    nodes = cast("dict[NodeId, dict[str, Any]]", payload["nodes"])
    path_ids: dict[str, NodeId] = {}
    visited: set[tuple[NodeId, str]] = set()

    def visit(node_id: NodeId, path: str) -> None:
        marker = (node_id, path)
        if marker in visited or node_id not in nodes:
            return
        visited.add(marker)
        node = nodes[node_id]
        kind = node["kind"]

        if kind in _PATH_TRACKED_KINDS:
            path_ids[path] = node_id
            return

        if kind == "contextvar":
            visit(node["value"], f"{path}.value")
            return

        if kind == "dict":
            for index, (key_id, value_id) in enumerate(node["entries"]):
                visit(key_id, f"{path}.key[{index}]")
                visit(value_id, f"{path}[{index}]")
            return

        if kind in {"list", "tuple", "set", "frozenset"}:
            for index, child_id in enumerate(node["items"]):
                visit(child_id, f"{path}[{index}]")
            return

        if kind == "object":
            for attr_name, child_id in node["attrs"].items():
                visit(child_id, f"{path}.{attr_name}")

    root_items = cast("dict[str, NodeId]", payload["root_ids"]).items()
    for root_key, node_id in root_items:
        visit(node_id, root_key)

    return path_ids


class SyncGraph:
    """Canonical CRDT graph for one resolver's resource state."""

    def __init__(
        self,
        *,
        actor_id: int,
        object_ids: dict[int, NodeId] | None = None,
        path_ids: dict[str, NodeId] | None = None,
        next_local_id: int | None = None,
    ) -> None:
        self.actor_id = actor_id
        self.object_ids = dict(object_ids or {})
        self.path_ids = dict(path_ids or {})
        self.next_local_id = next_local_id or _next_local_counter(
            actor_id,
            object_ids=self.object_ids,
            path_ids=self.path_ids,
        )
        self.doc = Doc(client_id=actor_id)
        self.roots = self.doc.get("roots", type=Map)
        self.nodes = self.doc.get("nodes", type=Map)
        self.ignored = self.doc.get("ignored", type=Map)
        self._baseline_root_ids: dict[str, NodeId] = {}
        self._baseline_nodes: dict[NodeId, dict[str, Any]] = {}
        self._baseline_ignored: dict[str, list[str]] = {}

    @classmethod
    def from_update(
        cls,
        update: bytes,
        *,
        actor_id: int,
    ) -> SyncGraph:
        """Build a graph from a CRDT update blob."""
        graph = cls(actor_id=actor_id)
        if update:
            graph.doc.apply_update(update)
        return graph

    def clone(self) -> SyncGraph:
        """Clone the graph and its cached identity state."""
        clone = SyncGraph.from_update(
            self.doc.get_update(None),
            actor_id=self.actor_id,
        )
        clone.object_ids = dict(self.object_ids)
        clone.path_ids = dict(self.path_ids)
        clone.next_local_id = self.next_local_id
        object.__setattr__(
            clone,
            "_baseline_root_ids",
            dict(self._baseline_root_ids),
        )
        object.__setattr__(
            clone,
            "_baseline_nodes",
            dict(self._baseline_nodes),
        )
        object.__setattr__(
            clone,
            "_baseline_ignored",
            {
                root_key: list(attrs)
                for root_key, attrs in self._baseline_ignored.items()
            },
        )
        return clone

    def payload(
        self,
        root_keys: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Return a serializable payload for the selected roots."""
        selected_root_keys = (
            list(root_keys) if root_keys is not None else [*self.roots.keys()]
        )
        root_ids: dict[str, NodeId] = {}
        queue: list[NodeId] = []
        for root_key in selected_root_keys:
            if root_key not in self.roots:
                continue
            node_id = str(self.roots[root_key])
            root_ids[root_key] = node_id
            queue.append(node_id)

        nodes: dict[NodeId, dict[str, Any]] = {}
        visited: set[NodeId] = set()
        while queue:
            node_id = queue.pop()
            if node_id in visited or node_id not in self.nodes:
                continue
            visited.add(node_id)
            node_payload = self._node_payload(
                cast("Map[Any]", self.nodes[node_id])
            )
            nodes[node_id] = node_payload
            queue.extend(self._child_ids(node_payload))

        ignored_paths = {
            root_key: [
                str(item) for item in cast("Array[Any]", self.ignored[root_key])
            ]
            for root_key in root_ids
            if root_key in self.ignored
        }
        return {
            "root_ids": root_ids,
            "nodes": nodes,
            "ignored_paths": ignored_paths,
        }

    def sync_live_roots(self, roots: dict[str, Any]) -> dict[str, Any]:
        """Sync live roots into the CRDT graph and return the payload."""
        exporter = SnapshotExporter(
            actor_id=self.actor_id,
            known_ids=self.object_ids,
            known_paths=self.path_ids,
            next_id=self.next_local_id,
        )
        root_ids, nodes, ignored_paths = exporter.export_roots(roots)
        payload = {
            "root_ids": root_ids,
            "nodes": nodes,
            "ignored_paths": ignored_paths,
        }
        if self._baseline_payload(root_ids) != payload:
            self.sync_payload(payload)
        self.object_ids = exporter.object_ids
        self.path_ids = exporter.path_ids
        self.next_local_id = exporter.next_id
        return payload

    def sync_payload(self, payload: dict[str, Any]) -> None:
        """Apply a payload into the backing CRDT document."""
        self._sync_named_values(self.roots, payload["root_ids"])
        self._sync_ignored(payload["ignored_paths"])
        for node_id, node_payload in payload["nodes"].items():
            self._sync_node(node_id, node_payload)
        self.set_baseline(payload)

    def apply_update(self, update: bytes) -> None:
        """Apply a remote CRDT update to the graph."""
        if update:
            self.doc.apply_update(update)

    def set_baseline(self, payload: dict[str, Any]) -> None:
        """Store the payload as the current sync baseline."""
        root_ids = cast("dict[str, NodeId]", payload["root_ids"])
        ignored_paths = cast("dict[str, list[str]]", payload["ignored_paths"])

        for root_key, node_id in root_ids.items():
            self._baseline_root_ids[root_key] = node_id
            if root_key in ignored_paths:
                self._baseline_ignored[root_key] = list(ignored_paths[root_key])
            else:
                self._baseline_ignored.pop(root_key, None)

        self._baseline_nodes.update(
            cast("dict[NodeId, dict[str, Any]]", payload["nodes"])
        )

    def _baseline_payload(
        self,
        root_ids: dict[str, NodeId],
    ) -> dict[str, Any]:
        nodes: dict[NodeId, dict[str, Any]] = {}
        queue = list(root_ids.values())
        visited: set[NodeId] = set()

        while queue:
            node_id = queue.pop()
            if node_id in visited or node_id not in self._baseline_nodes:
                continue
            visited.add(node_id)
            node_payload = self._baseline_nodes[node_id]
            nodes[node_id] = node_payload
            queue.extend(self._child_ids(node_payload))

        return {
            "root_ids": dict(root_ids),
            "nodes": nodes,
            "ignored_paths": {
                root_key: list(self._baseline_ignored[root_key])
                for root_key in root_ids
                if root_key in self._baseline_ignored
            },
        }

    @staticmethod
    def _child_ids(node: dict[str, Any]) -> list[NodeId]:
        match node["kind"]:
            case "contextvar":
                return [cast("NodeId", node["value"])]
            case "dict":
                return [
                    child_id
                    for entry in cast("list[list[NodeId]]", node["entries"])
                    for child_id in entry
                ]
            case "list" | "tuple" | "set" | "frozenset":
                return list(cast("list[NodeId]", node["items"]))
            case "object":
                return list(cast("dict[str, NodeId]", node["attrs"]).values())
            case _:
                return []

    def _node_payload(  # noqa: C901, PLR0911
        self,
        node: Map[Any],
    ) -> dict[str, Any]:
        kind = str(node["kind"])
        match kind:
            case "value":
                return {
                    "kind": kind,
                    "value": _primitive(node["value"]),
                }
            case "pickle":
                return {
                    "kind": kind,
                    "data": _bytes(node["data"]),
                }
            case "bigint" | "uuid" | "date" | "datetime" | "time" | "timedelta":
                return {"kind": kind, "value": node["value"]}
            case "path":
                return {
                    "kind": kind,
                    "module": node["module"],
                    "qualname": node["qualname"],
                    "class_data": _bytes(node.get("class_data")),
                    "value": node["value"],
                }
            case "enum":
                return {
                    "kind": kind,
                    "module": node["module"],
                    "qualname": node["qualname"],
                    "class_data": _bytes(node.get("class_data")),
                    "member": node["member"],
                }
            case "opaque":
                return {
                    "kind": kind,
                    "module": node.get("module"),
                    "qualname": node.get("qualname"),
                    "display": node["display"],
                }
            case "contextvar":
                return {
                    "kind": kind,
                    "name": node["name"],
                    "value": str(node["value"]),
                }
            case "list" | "tuple":
                items = cast("Array[Any]", node["items"])
                return {
                    "kind": kind,
                    "items": [str(item) for item in items],
                }
            case "set" | "frozenset":
                items = cast("Map[Any]", node["items"])
                return {
                    "kind": kind,
                    "items": [str(items[key]) for key in sorted(items.keys())],
                }
            case "dict":
                entries = cast("Map[Any]", node["entries"])
                return {
                    "kind": kind,
                    "entries": [
                        [str(key_id), str(entries[key_id])]
                        for key_id in sorted(entries.keys())
                    ],
                }
            case "object":
                attrs = cast("Map[Any]", node["attrs"])
                return {
                    "kind": kind,
                    "module": node["module"],
                    "qualname": node["qualname"],
                    "class_data": _bytes(node.get("class_data")),
                    "attrs": {
                        name: str(value) for name, value in attrs.items()
                    },
                }
            case _:
                msg = f"Unsupported node kind: {kind}"
                raise ValueError(msg)

    def _sync_named_values(
        self,
        target: Map[Any],
        values: dict[str, NodeId],
    ) -> None:
        for key, value in values.items():
            target[key] = value

    def _sync_ignored(self, ignored_paths: dict[str, list[str]]) -> None:
        for root_key, attrs in ignored_paths.items():
            if not attrs:
                if root_key in self.ignored:
                    del self.ignored[root_key]
                continue
            array = self._ensure_array(self.ignored, root_key)
            self._sync_string_array(array, attrs)

    def _sync_node(  # noqa: C901, PLR0912
        self,
        node_id: NodeId,
        payload: dict[str, Any],
    ) -> None:
        if self._baseline_nodes.get(node_id) == payload:
            return

        if node_id in self.nodes:
            record = cast("Map[Any]", self.nodes[node_id])
        else:
            record = self._ensure_map(self.nodes, node_id)
        kind = payload["kind"]
        record["kind"] = kind

        match kind:
            case "value":
                record["value"] = payload["value"]
            case "pickle":
                record["data"] = payload["data"]
            case "bigint" | "uuid" | "date" | "datetime" | "time" | "timedelta":
                record["value"] = payload["value"]
            case "path":
                self._sync_class_fields(record, payload)
                record["value"] = payload["value"]
            case "enum":
                self._sync_class_fields(record, payload)
                record["member"] = payload["member"]
            case "opaque":
                record["module"] = payload.get("module")
                record["qualname"] = payload.get("qualname")
                record["display"] = payload["display"]
            case "contextvar":
                record["name"] = payload["name"]
                record["value"] = payload["value"]
            case "list" | "tuple":
                items = self._ensure_array(record, "items")
                self._sync_string_array(items, payload["items"])
            case "set" | "frozenset":
                items = self._ensure_map(record, "items")
                self._sync_string_map(
                    items,
                    {item_id: item_id for item_id in payload["items"]},
                )
            case "dict":
                entries = self._ensure_map(record, "entries")
                self._sync_string_map(
                    entries,
                    dict(payload["entries"]),
                )
            case "object":
                self._sync_class_fields(record, payload)
                attrs = self._ensure_map(record, "attrs")
                self._sync_string_map(attrs, payload["attrs"])
            case _:
                msg = f"Unsupported node kind: {kind}"
                raise ValueError(msg)

    @staticmethod
    def _sync_class_fields(
        record: Map[Any],
        payload: dict[str, Any],
    ) -> None:
        record["module"] = payload["module"]
        record["qualname"] = payload["qualname"]
        record["class_data"] = payload.get("class_data")

    @staticmethod
    def _ensure_map(container: Map[Any], key: str) -> Map[Any]:
        current = container.get(key)
        if isinstance(current, Map):
            return current
        child = Map()
        container[key] = child
        return child

    @staticmethod
    def _ensure_array(container: Map[Any], key: str) -> Array[Any]:
        current = container.get(key)
        if isinstance(current, Array):
            return current
        child = Array()
        container[key] = child
        return child

    @staticmethod
    def _sync_string_map(
        target: Map[Any],
        values: dict[str, str],
    ) -> None:
        for key in list(target.keys()):
            if key not in values:
                del target[key]
        for key, value in values.items():
            target[key] = value

    @staticmethod
    def _sync_string_array(
        target: Array[Any],
        values: list[str],
    ) -> None:
        current = [str(item) for item in target]
        if current == values:
            return

        prefix = 0
        while prefix < len(current) and prefix < len(values):
            if current[prefix] != values[prefix]:
                break
            prefix += 1

        suffix = 0
        while (
            suffix < len(current) - prefix
            and suffix < len(values) - prefix
            and current[-(suffix + 1)] == values[-(suffix + 1)]
        ):
            suffix += 1

        current_end = len(current) - suffix
        next_values = values[prefix : len(values) - suffix]
        delete_count = current_end - prefix
        if delete_count > 0:
            del target[prefix:current_end]
        for offset, value in enumerate(next_values):
            target.insert(prefix + offset, value)
