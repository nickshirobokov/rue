"""Runtime-scoped patch dispatch."""

from __future__ import annotations

import inspect
from collections.abc import Iterator, MutableMapping, MutableSequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID

from rue.context.scopes import Scope, ScopeOwner


type PatchTargetKind = Literal["attr", "item"]
type PatchTargetKey = tuple[PatchTargetKind, int, Any]


_MISSING = object()


@dataclass(frozen=True, slots=True)
class PatchContext:
    """Context used by dispatchers while one test body is running."""

    execution_id: UUID | None
    module_path: Path
    run_id: UUID | None


@dataclass(frozen=True, slots=True)
class PatchLifetime:
    """Owner and storage API for one monkeypatch resource."""

    owner: ScopeOwner
    store: PatchStore

    @property
    def scope(self) -> Scope:
        """Return the lifecycle scope for this patch lifetime."""
        return self.owner.scope

    def register(self, handle: PatchHandle) -> None:
        """Register a patch handle with this lifetime's storage."""
        self.store.register_patch(handle)


@dataclass(frozen=True, slots=True)
class PatchHandle:
    """A registered patch that can be undone by its owning resolver."""

    owner: ScopeOwner
    target_key: PatchTargetKey
    record: _PatchRecord
    manager: PatchManager

    def undo(self) -> None:
        """Remove this patch record from its target dispatcher."""
        self.manager.remove(self)


@dataclass(slots=True)
class PatchStore:
    """Stores patch handles by their patch lifecycle owner."""

    _handles: dict[ScopeOwner, list[PatchHandle]] = field(
        default_factory=dict
    )

    def lifetime(self, owner: ScopeOwner) -> PatchLifetime:
        """Build a lifetime API for one patch owner."""
        return PatchLifetime(owner=owner, store=self)

    def register_patch(self, handle: PatchHandle) -> None:
        """Attach a patch handle to its owning patch lifecycle."""
        self._handles.setdefault(handle.owner, []).append(handle)

    def pop_owner(self, owner: ScopeOwner) -> list[PatchHandle]:
        """Remove and return patch handles for one owner."""
        return self._handles.pop(owner, [])

    def pop_scope(self, scope: Scope) -> list[PatchHandle]:
        """Remove and return patch handles for all owners in one scope."""
        handles: list[PatchHandle] = []
        for owner in tuple(self._handles):
            if owner.scope is scope:
                handles.extend(self.pop_owner(owner))
        return handles

    def pop_all(self) -> list[PatchHandle]:
        """Remove and return all patch handles."""
        handles: list[PatchHandle] = []
        for owner in tuple(self._handles):
            handles.extend(self.pop_owner(owner))
        return handles


@dataclass(slots=True)
class _PatchRecord:
    owner: ScopeOwner
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
        owner: ScopeOwner,
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
        owner: ScopeOwner,
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
        owner: ScopeOwner,
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
        owner: ScopeOwner,
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
        owner: ScopeOwner,
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
                if context is not None and record.owner.is_active(
                    execution_id=context.execution_id,
                    run_id=context.run_id,
                    module_path=context.module_path,
                ):
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
