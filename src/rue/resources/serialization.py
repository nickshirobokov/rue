"""Serialization helpers for resource transfer.

Inspect logic is adapted from Ray (Apache-2.0,
``python/ray/util/check_serialize.py``), exposed upstream as
``ray.util.inspect_serializability``: same closure/member walk and
``dumps`` probe via ``cloudpickle``, without Ray workers or serializers.
"""

from __future__ import annotations

import inspect
import io
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, cast

import cloudpickle


@contextmanager
def _indent(printer: _Printer) -> Iterator[None]:
    printer.level += 1
    yield
    printer.level -= 1


class _Printer:
    def __init__(self, print_file: Any) -> None:
        self.level = 0
        self.print_file = print_file

    def indent(self) -> AbstractContextManager[None]:
        return _indent(self)

    def print(self, msg: str) -> None:
        indent = "    " * self.level
        print(indent + msg, file=self.print_file)


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
    printer: _Printer,
) -> bool:
    """Adds the first-found non-serializable element to the failure_set."""
    assert inspect.isfunction(base_obj)
    closure = inspect.getclosurevars(base_obj)
    found = False
    if closure.globals:
        printer.print(
            f"Detected {len(closure.globals)} global variables. "
            "Checking serializability..."
        )

        with printer.indent():
            for name, obj in closure.globals.items():
                serializable, _ = _inspect_serializability(
                    obj,
                    name=name,
                    depth=depth - 1,
                    parent=parent,
                    failure_set=failure_set,
                    printer=printer,
                )
                found = found or not serializable
                if found:
                    break

    if closure.nonlocals:
        printer.print(
            f"Detected {len(closure.nonlocals)} nonlocal variables. "
            "Checking serializability..."
        )
        with printer.indent():
            for name, obj in closure.nonlocals.items():
                serializable, _ = _inspect_serializability(
                    obj,
                    name=name,
                    depth=depth - 1,
                    parent=parent,
                    failure_set=failure_set,
                    printer=printer,
                )
                found = found or not serializable
                if found:
                    break
    if not found:
        printer.print(
            f"WARNING: Did not find non-serializable object in {base_obj}. "
            "This may be an oversight."
        )
    return found


def _inspect_generic_serialization(
    base_obj: Any,
    depth: int,
    parent: Any,
    failure_set: set[FailureTuple],
    printer: _Printer,
) -> bool:
    """Adds the first-found non-serializable element to the failure_set."""
    assert not inspect.isfunction(base_obj)
    functions = inspect.getmembers(base_obj, predicate=inspect.isfunction)
    found = False
    with printer.indent():
        for name, obj in functions:
            serializable, _ = _inspect_serializability(
                obj,
                name=name,
                depth=depth - 1,
                parent=parent,
                failure_set=failure_set,
                printer=printer,
            )
            found = found or not serializable
            if found:
                break

    with printer.indent():
        members = inspect.getmembers(base_obj)
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
                printer=printer,
            )
            found = found or not serializable
            if found:
                break
    if not found:
        printer.print(
            f"WARNING: Did not find non-serializable object in {base_obj}. "
            "This may be an oversight."
        )
    return found


def inspect_serializability(
    base_obj: Any,
    name: str | None = None,
    depth: int = 3,
    print_file: Any | None = None,
) -> tuple[bool, set[FailureTuple]]:
    """Identifies what objects are preventing ``cloudpickle`` serialization."""
    printer = _Printer(print_file)
    return _inspect_serializability(base_obj, name, depth, None, None, printer)


def _inspect_serializability(
    base_obj: Any,
    name: str | None,
    depth: int,
    parent: Any,
    failure_set: set[FailureTuple] | None,
    printer: _Printer,
) -> tuple[bool, set[FailureTuple]]:
    top_level = False
    declaration = ""
    found = False
    if failure_set is None:
        top_level = True
        failure_set = set()
        declaration = f"Checking Serializability of {base_obj}"
        printer.print("=" * min(len(declaration), 80))
        printer.print(declaration)
        printer.print("=" * min(len(declaration), 80))

        if name is None:
            name = str(base_obj)
    else:
        printer.print(f"Serializing '{name}' {base_obj}...")
    try:
        cloudpickle.dumps(base_obj)
        return True, failure_set
    except Exception as e:
        printer.print(f"!!! FAIL serialization: {e}")
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
            printer=printer,
        )
    else:
        _inspect_generic_serialization(
            base_obj,
            depth=depth,
            parent=base_obj,
            failure_set=failure_set,
            printer=printer,
        )

    if not failure_set:
        fail_name = name if name is not None else ""
        failure_set.add(FailureTuple(base_obj, fail_name, parent))

    if top_level:
        printer.print("=" * min(len(declaration), 80))
        if not failure_set:
            printer.print(
                "Nothing failed the inspect_serialization test, though "
                "serialization did not succeed."
            )
        else:
            joined = "\n".join(str(k) for k in failure_set)
            fail_vars = f"\n\n\t{joined}\n\n"
            printer.print(
                f"Variable: {fail_vars}was found to be non-serializable. "
                "There may be multiple other undetected variables that were "
                "non-serializable. "
            )
            printer.print(
                "Consider either removing the "
                "instantiation/imports of these variables or moving the "
                "instantiation into the scope of the function/class. "
            )
        printer.print("=" * min(len(declaration), 80))
        printer.print(
            "See cloudpickle and pickle documentation for serialization limits."
        )
        printer.print("=" * min(len(declaration), 80))
    return not found, failure_set


def check_serializable(value: Any) -> bool:
    """Check if a value can be safely serialized."""
    buffer = io.StringIO()
    is_serializable, _ = inspect_serializability(value, print_file=buffer)
    return is_serializable


def serialize_value(value: Any) -> bytes:
    """Serialize a value to bytes."""
    return cast("bytes", cloudpickle.dumps(value))


def deserialize_value(data: bytes) -> Any:
    """Deserialize bytes back to a value."""
    return cast("Any", cloudpickle.loads(data))
