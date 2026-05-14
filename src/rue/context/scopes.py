"""Runtime scope ownership models."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from types import TracebackType
from uuid import UUID

from rue.context.models import ScopeOwner


class Scope(StrEnum):
    """DI lifecycle scope."""

    TEST = auto()  # Fresh instance per test
    MODULE = auto()  # Shared across tests in same file
    SUITE = auto()  # Shared across entire suite execution

    @classmethod
    def provider_priority(cls) -> tuple[Scope, ...]:
        """Return provider lookup order from narrowest to broadest scope."""
        return tuple(cls)

    @property
    def dependency_scopes(self) -> frozenset[Scope]:
        """Return scopes this scope may depend on."""
        scopes = tuple(type(self))
        return frozenset(scopes[scopes.index(self) :])


class CurrentProcessKind(StrEnum):
    """Runtime process kind for the active suite context."""

    MAIN = auto()
    TEST_SUBPROCESS = auto()
    EXPERIMENT_SUBPROCESS = auto()


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """Current runtime owners for resolved injected dependencies."""

    suite: ScopeOwner
    test: ScopeOwner | None = None
    module: ScopeOwner | None = None
    _tokens: list[Token[ScopeContext]] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def for_suite(cls, suite_execution_id: UUID) -> ScopeContext:
        """Build a scope context for suite-scoped work."""
        return cls(
            suite=ScopeOwner(
                scope=Scope.SUITE,
                suite_execution_id=suite_execution_id,
            )
        )

    @classmethod
    def for_module(
        cls,
        suite_execution_id: UUID,
        module_path: Path,
    ) -> ScopeContext:
        """Build a scope context for module-scoped work."""
        return cls(
            suite=ScopeOwner(
                scope=Scope.SUITE,
                suite_execution_id=suite_execution_id,
            ),
            module=ScopeOwner(
                scope=Scope.MODULE,
                suite_execution_id=suite_execution_id,
                module_path=module_path,
            ),
        )

    @classmethod
    def for_test(cls, test_execution_id: UUID) -> ScopeContext:
        """Build a scope context for test-scoped work."""
        current = cls.current()
        return cls(
            suite=current.suite,
            test=ScopeOwner(
                scope=Scope.TEST,
                test_execution_id=test_execution_id,
                suite_execution_id=current.suite.suite_execution_id,
            ),
            module=current.module,
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
            case Scope.SUITE:
                return self.suite
            case Scope.TEST:
                if self.test is None:
                    msg = "Test-scoped resources require an open TestContext."
                    raise RuntimeError(msg)
                return self.test
            case Scope.MODULE:
                if self.module is None:
                    msg = (
                        "Module-scoped resources require an open "
                        "ModuleContext or TestContext."
                    )
                    raise RuntimeError(msg)
                return self.module

    def __enter__(self) -> ScopeContext:
        """Bind this scope context to the current runtime ownership scope."""
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
