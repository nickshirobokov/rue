"""Runtime scope ownership models."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from types import TracebackType
from uuid import UUID


class Scope(StrEnum):
    """DI lifecycle scope."""

    TEST = auto()  # Fresh instance per test
    MODULE = auto()  # Shared across tests in same file
    RUN = auto()  # Shared across entire test run


@dataclass(frozen=True, slots=True)
class ScopeOwner:
    """Runtime owner for resolved injected dependencies."""

    scope: Scope
    execution_id: UUID | None = None
    run_id: UUID | None = None
    module_path: Path | None = None

    def is_active(
        self,
        *,
        execution_id: UUID | None,
        run_id: UUID | None,
        module_path: Path | None,
    ) -> bool:
        """Return whether this owner applies in the current runtime context."""
        match self.scope:
            case Scope.TEST:
                return (
                    self.execution_id is not None
                    and self.run_id is not None
                    and execution_id == self.execution_id
                    and run_id == self.run_id
                )
            case Scope.MODULE:
                return (
                    self.module_path is not None
                    and self.run_id is not None
                    and module_path == self.module_path
                    and run_id == self.run_id
                )
            case Scope.RUN:
                return self.run_id is not None and run_id == self.run_id


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """Current runtime owners for resolved injected dependencies."""

    run: ScopeOwner
    test: ScopeOwner | None = None
    module: ScopeOwner | None = None
    _tokens: list[Token[ScopeContext]] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def for_run(cls, run_id: UUID) -> ScopeContext:
        """Build a scope context for run-scoped work."""
        return cls(run=ScopeOwner(scope=Scope.RUN, run_id=run_id))

    @classmethod
    def for_test(
        cls,
        run_id: UUID,
        execution_id: UUID,
        module_path: Path,
    ) -> ScopeContext:
        """Build a scope context for test-scoped work."""
        resolved_module_path = module_path.resolve()
        return cls(
            run=ScopeOwner(scope=Scope.RUN, run_id=run_id),
            test=ScopeOwner(
                scope=Scope.TEST,
                execution_id=execution_id,
                run_id=run_id,
            ),
            module=ScopeOwner(
                scope=Scope.MODULE,
                run_id=run_id,
                module_path=resolved_module_path,
            ),
        )

    @classmethod
    def current(cls) -> ScopeContext:
        """Return the current scope context."""
        return CURRENT_SCOPE_CONTEXT.get()

    @classmethod
    def current_owner(cls, scope: Scope) -> ScopeOwner:
        """Return the current owner for a scope."""
        return cls.current().owner(scope)

    def owner(self, scope: Scope) -> ScopeOwner:
        """Return the owner for a scope in this context."""
        match scope:
            case Scope.RUN:
                return self.run
            case Scope.TEST:
                if self.test is None:
                    msg = "Test-scoped resources require an open TestContext."
                    raise RuntimeError(msg)
                return self.test
            case Scope.MODULE:
                if self.module is None:
                    msg = (
                        "Module-scoped resources require an open TestContext."
                    )
                    raise RuntimeError(msg)
                return self.module

    def __enter__(self) -> ScopeContext:
        """Bind this scope context to the current execution scope."""
        self._tokens.append(CURRENT_SCOPE_CONTEXT.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous scope context."""
        CURRENT_SCOPE_CONTEXT.reset(self._tokens.pop())


CURRENT_SCOPE_CONTEXT: ContextVar[ScopeContext] = ContextVar(
    "current_scope_context"
)
