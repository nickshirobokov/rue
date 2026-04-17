"""Serialization helpers for resource transfer."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import cloudpickle


def _safe_getmembers(
    obj: Any,
    predicate: Callable[[Any], bool] | None = None,
) -> list[tuple[str, Any]]:
    """Like ``inspect.getmembers``, but skips names whose ``getattr`` raises."""
    results: list[tuple[str, Any]] = []
    for key in dir(obj):
        try:
            value = getattr(obj, key)
        except Exception:
            continue
        if predicate is None or predicate(value):
            results.append((key, value))
    results.sort(key=lambda item: item[0])
    return results


class FailureTuple:
    """Serialization failure frame (same shape as Ray's ``FailureTuple``)."""

    def __init__(self, obj: Any, name: str, parent: Any) -> None:
        self.obj = obj
        self.name = name
        self.parent = parent

    def __repr__(self) -> str:
        return f"FailTuple({self.name} [obj={self.obj}, parent={self.parent}])"


def _inspect_func_serialization(
    base_obj: Any,
    depth: int,
    parent: Any,
    failure_set: set[FailureTuple],
) -> bool:
    """Adds the first-found non-serializable element to the failure_set."""
    assert inspect.isfunction(base_obj)
    closure = inspect.getclosurevars(base_obj)
    found = False
    if closure.globals:
        for name, obj in closure.globals.items():
            serializable, _ = _inspect_serializability(
                obj,
                name=name,
                depth=depth - 1,
                parent=parent,
                failure_set=failure_set,
            )
            found = found or not serializable
            if found:
                break

    if closure.nonlocals:
        for name, obj in closure.nonlocals.items():
            serializable, _ = _inspect_serializability(
                obj,
                name=name,
                depth=depth - 1,
                parent=parent,
                failure_set=failure_set,
            )
            found = found or not serializable
            if found:
                break
    return found


def _inspect_generic_serialization(
    base_obj: Any,
    depth: int,
    parent: Any,
    failure_set: set[FailureTuple],
) -> bool:
    """Adds the first-found non-serializable element to the failure_set."""
    assert not inspect.isfunction(base_obj)
    functions = _safe_getmembers(base_obj, predicate=inspect.isfunction)
    found = False
    for name, obj in functions:
        serializable, _ = _inspect_serializability(
            obj,
            name=name,
            depth=depth - 1,
            parent=parent,
            failure_set=failure_set,
        )
        found = found or not serializable
        if found:
            break

    members = _safe_getmembers(base_obj)
    for name, obj in members:
        dunder = name.startswith("__") and name.endswith("__")
        if dunder or inspect.isbuiltin(obj):
            continue
        serializable, _ = _inspect_serializability(
            obj,
            name=name,
            depth=depth - 1,
            parent=parent,
            failure_set=failure_set,
        )
        found = found or not serializable
        if found:
            break
    return found


def inspect_serializability(
    base_obj: Any,
    name: str | None = None,
    depth: int = 3,
) -> tuple[bool, set[FailureTuple]]:
    """Identifies what objects are preventing ``cloudpickle`` serialization."""
    return _inspect_serializability(base_obj, name, depth, None, None)


def _inspect_serializability(
    base_obj: Any,
    name: str | None,
    depth: int,
    parent: Any,
    failure_set: set[FailureTuple] | None,
) -> tuple[bool, set[FailureTuple]]:
    found = False
    if failure_set is None:
        failure_set = set()
        if name is None:
            name = str(base_obj)
    try:
        cloudpickle.dumps(base_obj)
        return True, failure_set
    except Exception:
        found = True
        try:
            if depth == 0:
                fail_name = name if name is not None else ""
                failure_set.add(FailureTuple(base_obj, fail_name, parent))
        except Exception:
            pass

    if depth <= 0:
        return False, failure_set

    if inspect.isfunction(base_obj):
        _inspect_func_serialization(
            base_obj,
            depth=depth,
            parent=base_obj,
            failure_set=failure_set,
        )
    else:
        _inspect_generic_serialization(
            base_obj,
            depth=depth,
            parent=base_obj,
            failure_set=failure_set,
        )

    if not failure_set:
        fail_name = name if name is not None else ""
        failure_set.add(FailureTuple(base_obj, fail_name, parent))

    return not found, failure_set


def check_serializable(value: Any) -> bool:
    """Check if a value can be safely serialized."""
    is_serializable, _ = inspect_serializability(value)
    return is_serializable


def serialize_value(value: Any) -> bytes:
    """Serialize a value to bytes."""
    return cloudpickle.dumps(value)


def deserialize_value(data: bytes) -> Any:
    """Deserialize bytes back to a value."""
    return cloudpickle.loads(data)
