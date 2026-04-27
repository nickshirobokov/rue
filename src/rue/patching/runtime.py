"""Runtime-scoped patch dispatch."""

from __future__ import annotations

import inspect
from collections.abc import Iterator, MutableMapping, MutableSequence
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID

from rue.context.runtime import (
    CURRENT_RESOURCE_RESOLVER,
    CURRENT_RUN_CONTEXT,
    CURRENT_TEST,
)
from rue.resources.models import Scope


type PatchTargetKind = Literal["attr", "item"]
type PatchTargetKey = tuple[PatchTargetKind, int, Any]


_MISSING = object()


@dataclass(frozen=True, slots=True)
class PatchContext:
    """Context used by dispatchers while one test body is running."""

    execution_id: UUID | None
    module_path: Path
    resources: frozenset[Any]


@dataclass(frozen=True, slots=True)
class PatchOwner:
    """Owns visibility and cleanup for one patch record."""

    scope: Scope
    execution_id: UUID | None = None
    run_id: UUID | None = None
    module_path: Path | None = None

    def is_active(self, _context: PatchContext | None) -> bool:
        """Return whether this owner applies in the current runtime context."""
        test_ctx = CURRENT_TEST.get()
        match self.scope:
            case Scope.TEST:
                return (
                    self.execution_id is not None
                    and test_ctx is not None
                    and test_ctx.execution_id == self.execution_id
                )
            case Scope.MODULE:
                return (
                    self.module_path is not None
                    and test_ctx is not None
                    and test_ctx.item.spec.module_path.resolve()
                    == self.module_path
                )
            case Scope.RUN:
                run_context = CURRENT_RUN_CONTEXT.get()
                run_id = None if run_context is None else run_context.run_id
                return self.run_id is not None and run_id == self.run_id

    @classmethod
    def build(cls, scope: Scope) -> PatchOwner:
        """Build an owner from the current Rue runtime context."""
        test_ctx = CURRENT_TEST.get()
        match scope:
            case Scope.TEST:
                if test_ctx is None:
                    raise RuntimeError(
                        "Test-scoped patches require a Rue test context."
                    )
                return cls(
                    scope=Scope.TEST, execution_id=test_ctx.execution_id
                )
            case Scope.MODULE:
                if test_ctx is None:
                    raise RuntimeError(
                        "Module-scoped patches require a Rue test context."
                    )
                return cls(
                    scope=Scope.MODULE,
                    module_path=test_ctx.item.spec.module_path.resolve(),
                )
            case Scope.RUN:
                run_context = CURRENT_RUN_CONTEXT.get()
                run_id = None if run_context is None else run_context.run_id
                if run_id is None:
                    raise RuntimeError(
                        "Run-scoped patches require a Rue run context."
                    )
                return cls(scope=Scope.RUN, run_id=run_id)


@dataclass(frozen=True, slots=True)
class PatchHandle:
    """A registered patch that can be undone by its owning resolver."""

    owner: PatchOwner
    target_key: PatchTargetKey
    record: _PatchRecord
    manager: PatchManager

    def undo(self) -> None:
        """Remove this patch record from its target dispatcher."""
        self.manager.remove(self)

    def register_to_resolver(self) -> None:
        """Attach this handle to the current resolver or undo and raise."""
        resolver = CURRENT_RESOURCE_RESOLVER.get()
        if resolver is None:
            self.undo()
            raise RuntimeError(
                "MonkeyPatch can only be used inside Rue execution."
            )
        resolver.register_patch(self)


@dataclass(slots=True)
class _PatchRecord:
    owner: PatchOwner
    value: Any


@dataclass(slots=True)
class _PatchedTarget:
    kind: PatchTargetKind
    target: Any
    name: Any
    original: Any
    dispatcher: Any
    records: list[_PatchRecord]


class _AttributeDispatcher:
    """Descriptor/proxy installed once per patched attribute."""

    def __init__(
        self,
        manager: PatchManager,
        target_key: PatchTargetKey,
    ) -> None:
        self._manager = manager
        self._target_key = target_key

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Any:
        value = self._active_value()
        descriptor_get = getattr(type(value), "__get__", None)
        if descriptor_get is None:
            return value
        return descriptor_get(value, instance, owner)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._active_value()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._active_value(), name)

    def __repr__(self) -> str:
        return repr(self._active_value())

    def __str__(self) -> str:
        return str(self._active_value())

    def __bool__(self) -> bool:
        return bool(self._active_value())

    def __eq__(self, other: object) -> bool:
        return bool(self._active_value() == other)

    def __ne__(self, other: object) -> bool:
        return bool(self._active_value() != other)

    def __len__(self) -> int:
        return len(self._active_value())

    def __iter__(self) -> Iterator[Any]:
        return iter(self._active_value())

    def __contains__(self, item: object) -> bool:
        return item in self._active_value()

    def __getitem__(self, key: Any) -> Any:
        return self._active_value()[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self._active_value()[key] = value

    def _active_value(self) -> Any:
        return self._manager.active_value(self._target_key)


class _ItemDispatcher(_AttributeDispatcher):
    """Proxy installed once per patched mapping item."""


class PatchManager:
    """Installs dispatchers and routes patched values by Rue context."""

    def __init__(self) -> None:
        self._patched: dict[PatchTargetKey, _PatchedTarget] = {}
        self._lock = RLock()
        self._context: ContextVar[PatchContext | None] = ContextVar(
            "rue_patch_context",
            default=None,
        )

    @property
    def context(self) -> PatchContext | None:
        """Return the patch context active in this execution context."""
        return self._context.get()

    def bind_context(
        self,
        context: PatchContext | None,
    ) -> _PatchContextToken:
        """Bind a patch context for one test body."""
        return _PatchContextToken(self, self._context.set(context))

    def setattr(
        self,
        target: Any,
        name: str,
        value: Any,
        *,
        owner: PatchOwner,
        raising: bool,
    ) -> PatchHandle:
        """Install or append one context-routed attribute patch."""
        target_key: PatchTargetKey = ("attr", id(target), name)
        with self._lock:
            patched = self._patched.get(target_key)
            if patched is None:
                try:
                    original = inspect.getattr_static(target, name)
                except AttributeError:
                    if raising:
                        raise
                    original = _MISSING
                dispatcher = _AttributeDispatcher(self, target_key)
                patched = _PatchedTarget(
                    kind="attr",
                    target=target,
                    name=name,
                    original=original,
                    dispatcher=dispatcher,
                    records=[],
                )
                self._patched[target_key] = patched
                setattr(target, name, dispatcher)

            return self._add_record(patched, owner, value)

    def delattr(
        self,
        target: Any,
        name: str,
        *,
        owner: PatchOwner,
        raising: bool,
    ) -> PatchHandle | None:
        """Install or append one context-routed attribute deletion."""
        target_key: PatchTargetKey = ("attr", id(target), name)
        with self._lock:
            patched = self._patched.get(target_key)
            if patched is None:
                try:
                    original = inspect.getattr_static(target, name)
                except AttributeError:
                    if raising:
                        raise
                    return None
                dispatcher = _AttributeDispatcher(self, target_key)
                patched = _PatchedTarget(
                    kind="attr",
                    target=target,
                    name=name,
                    original=original,
                    dispatcher=dispatcher,
                    records=[],
                )
                self._patched[target_key] = patched
                setattr(target, name, dispatcher)

            return self._add_record(patched, owner, _MISSING)

    def setitem(
        self,
        target: MutableMapping[Any, Any] | MutableSequence[Any],
        name: Any,
        value: Any,
        *,
        owner: PatchOwner,
        replace: bool | None = None,
    ) -> PatchHandle:
        """Install or append one context-routed item patch."""
        target_key: PatchTargetKey = ("item", id(target), name)
        with self._lock:
            patched = self._patched.get(target_key)
            if patched is None:
                if isinstance(target, MutableSequence):
                    if replace:
                        original = target[name]
                    else:
                        original = _MISSING
                else:
                    original = target.get(name, _MISSING)

                dispatcher = _ItemDispatcher(self, target_key)
                patched = _PatchedTarget(
                    kind="item",
                    target=target,
                    name=name,
                    original=original,
                    dispatcher=dispatcher,
                    records=[],
                )
                self._patched[target_key] = patched
                if isinstance(target, MutableSequence) and not replace:
                    target.insert(name, dispatcher)
                else:
                    target[name] = dispatcher

            return self._add_record(patched, owner, value)

    def delitem(
        self,
        target: MutableMapping[Any, Any] | MutableSequence[Any],
        name: Any,
        *,
        owner: PatchOwner,
        raising: bool,
    ) -> PatchHandle | None:
        """Install or append one context-routed item deletion."""
        target_key: PatchTargetKey = ("item", id(target), name)
        with self._lock:
            patched = self._patched.get(target_key)
            if patched is None:
                if isinstance(target, MutableSequence):
                    try:
                        original = target[name]
                    except IndexError:
                        if raising:
                            raise
                        return None
                else:
                    if name not in target:
                        if raising:
                            raise KeyError(name)
                        return None
                    original = target[name]

                dispatcher = _ItemDispatcher(self, target_key)
                patched = _PatchedTarget(
                    kind="item",
                    target=target,
                    name=name,
                    original=original,
                    dispatcher=dispatcher,
                    records=[],
                )
                self._patched[target_key] = patched
                target[name] = dispatcher

            return self._add_record(patched, owner, _MISSING)

    def _add_record(
        self,
        patched: _PatchedTarget,
        owner: PatchOwner,
        value: Any,
    ) -> PatchHandle:
        record = _PatchRecord(owner=owner, value=value)
        patched.records.append(record)
        return PatchHandle(
            owner=owner,
            target_key=(patched.kind, id(patched.target), patched.name),
            record=record,
            manager=self,
        )

    def active_value(self, target_key: PatchTargetKey) -> Any:
        """Return the currently visible value for a patched target."""
        with self._lock:
            patched = self._patched[target_key]
            context = self._context.get()
            for record in reversed(patched.records):
                if record.owner.is_active(context):
                    if record.value is _MISSING:
                        self._raise_missing(patched)
                    return record.value
            if patched.original is _MISSING:
                self._raise_missing(patched)
            return patched.original

    def remove(self, handle: PatchHandle) -> None:
        """Remove one patch handle and restore the target when it is last."""
        with self._lock:
            patched = self._patched.get(handle.target_key)
            if patched is None:
                return
            if handle.record in patched.records:
                patched.records.remove(handle.record)
            if patched.records:
                return
            if patched.original is _MISSING:
                self._delete_target(patched)
            else:
                self._restore_target(patched)
            del self._patched[handle.target_key]

    @staticmethod
    def _raise_missing(patched: _PatchedTarget) -> None:
        match patched.kind:
            case "attr":
                msg = (
                    f"{patched.target!r} has no attribute {patched.name!r}"
                )
                raise AttributeError(msg)
            case "item":
                if isinstance(patched.target, MutableSequence):
                    raise IndexError(patched.name)
                raise KeyError(patched.name)

    @staticmethod
    def _delete_target(patched: _PatchedTarget) -> None:
        match patched.kind:
            case "attr":
                delattr(patched.target, patched.name)
            case "item":
                del patched.target[patched.name]

    @staticmethod
    def _restore_target(patched: _PatchedTarget) -> None:
        match patched.kind:
            case "attr":
                setattr(patched.target, patched.name, patched.original)
            case "item":
                patched.target[patched.name] = patched.original


class _PatchContextToken:
    def __init__(
        self,
        manager: PatchManager,
        token: Token[PatchContext | None],
    ) -> None:
        self._manager = manager
        self._token = token

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc_info: object) -> None:
        self._manager._context.reset(self._token)


patch_manager = PatchManager()
