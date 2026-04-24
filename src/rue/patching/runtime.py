"""Runtime-scoped attribute patch dispatch."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID

from rue.context.runtime import (
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_TEST,
)


type PatchScope = Literal["test", "resource", "module", "session"]


_MISSING = object()


@dataclass(frozen=True, slots=True)
class PatchContext:
    """Context used by dispatchers while one test body is running."""

    execution_id: UUID | None
    run_id: UUID | None
    module_path: Path
    resources: frozenset[Any]


@dataclass(frozen=True, slots=True)
class PatchOwner:
    """Owns visibility and cleanup for one patch record."""

    scope: PatchScope
    execution_id: UUID | None = None
    run_id: UUID | None = None
    module_path: Path | None = None
    resource: Any = None

    def is_active(self, context: PatchContext | None) -> bool:
        """Return whether this owner applies in the current runtime context."""
        test_ctx = CURRENT_TEST.get()
        provider = CURRENT_RESOURCE_PROVIDER.get()
        match self.scope:
            case "test":
                return (
                    self.execution_id is not None
                    and test_ctx is not None
                    and test_ctx.execution_id == self.execution_id
                )
            case "resource":
                return (
                    self.resource is not None
                    and (
                        (
                            provider is not None
                            and provider.spec == self.resource
                        )
                        or (
                            context is not None
                            and self.resource in context.resources
                        )
                    )
                )
            case "module":
                return (
                    self.module_path is not None
                    and test_ctx is not None
                    and test_ctx.item.spec.module_path.resolve()
                    == self.module_path
                )
            case "session":
                return (
                    self.run_id is not None
                    and test_ctx is not None
                    and test_ctx.run_id == self.run_id
                )

    @classmethod
    def build(cls, scope: PatchScope) -> PatchOwner:
        """Build an owner from the current Rue runtime context."""
        test_ctx = CURRENT_TEST.get()
        provider = CURRENT_RESOURCE_PROVIDER.get()
        match scope:
            case "test":
                if test_ctx is None:
                    raise RuntimeError(
                        "Test-scoped patches require a Rue test context."
                    )
                return cls(scope="test", execution_id=test_ctx.execution_id)
            case "resource":
                if provider is None:
                    raise RuntimeError(
                        "Resource-scoped patches require a Rue resource "
                        "context."
                    )
                return cls(scope="resource", resource=provider.spec)
            case "module":
                if test_ctx is None:
                    raise RuntimeError(
                        "Module-scoped patches require a Rue test context."
                    )
                return cls(
                    scope="module",
                    module_path=test_ctx.item.spec.module_path.resolve(),
                )
            case "session":
                if test_ctx is None or test_ctx.run_id is None:
                    raise RuntimeError(
                        "Session-scoped patches require a Rue run context."
                    )
                return cls(scope="session", run_id=test_ctx.run_id)


@dataclass(frozen=True, slots=True)
class PatchHandle:
    """A registered patch that can be undone by its owning resolver."""

    owner: PatchOwner
    target_key: tuple[int, str]
    record: _PatchRecord
    manager: PatchManager

    def undo(self) -> None:
        """Remove this patch record from its target dispatcher."""
        self.manager.remove(self)


@dataclass(slots=True)
class _PatchRecord:
    owner: PatchOwner
    value: Any


@dataclass(slots=True)
class _PatchedAttribute:
    target: Any
    name: str
    original: Any
    dispatcher: _AttributeDispatcher
    records: list[_PatchRecord]


class _AttributeDispatcher:
    """Descriptor/proxy installed once per patched attribute."""

    def __init__(
        self,
        manager: PatchManager,
        target_key: tuple[int, str],
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
        return self._active_value() == other

    def __ne__(self, other: object) -> bool:
        return self._active_value() != other

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


class PatchManager:
    """Installs dispatchers and routes patched attributes by Rue context."""

    def __init__(self) -> None:
        self._patched: dict[tuple[int, str], _PatchedAttribute] = {}
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
        target_key = (id(target), name)
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
                patched = _PatchedAttribute(
                    target=target,
                    name=name,
                    original=original,
                    dispatcher=dispatcher,
                    records=[],
                )
                self._patched[target_key] = patched
                setattr(target, name, dispatcher)

            record = _PatchRecord(owner=owner, value=value)
            patched.records.append(record)
            return PatchHandle(
                owner=owner,
                target_key=target_key,
                record=record,
                manager=self,
            )

    def active_value(self, target_key: tuple[int, str]) -> Any:
        """Return the currently visible value for a patched attribute."""
        with self._lock:
            patched = self._patched[target_key]
            context = self._context.get()
            for record in reversed(patched.records):
                if record.owner.is_active(context):
                    return record.value
            if patched.original is _MISSING:
                msg = f"{patched.target!r} has no attribute {patched.name!r}"
                raise AttributeError(msg)
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
                delattr(patched.target, patched.name)
            else:
                setattr(patched.target, patched.name, patched.original)
            del self._patched[handle.target_key]


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
