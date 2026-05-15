"""Runtime context variables for Rue suite and test execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from rue.config import Config
from rue.context.models import SuiteHost
from rue.context.scopes import CurrentProcessKind, ScopeContext
from rue.environment.storage import EnvironmentStorage
from rue.models import Spec


if TYPE_CHECKING:
    from rue.resources.models import ResourceSpec
    from rue.testing.tracing import TestTracer


@dataclass(slots=True)
class TestContext:
    """Runtime data owned by one executing test."""

    __test__ = False

    test_execution_id: UUID
    _tokens: list[Token[TestContext]] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )
    _scope_contexts: list[ScopeContext] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    def __enter__(self) -> TestContext:
        """Bind this test context to the current test execution scope."""
        self._tokens.append(TEST_EXECUTION_CONTEXT.set(self))
        scope_context = ScopeContext.for_test(self.test_execution_id)
        scope_context.__enter__()
        self._scope_contexts.append(scope_context)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous test context."""
        self._scope_contexts.pop().__exit__(exc_type, exc, traceback)
        TEST_EXECUTION_CONTEXT.reset(self._tokens.pop())


@dataclass(slots=True)
class ModuleContext:
    """Runtime data owned by work inside one test module."""

    module_path: Path
    _scope_contexts: list[ScopeContext] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    def __enter__(self) -> ModuleContext:
        """Bind this module context to the current module runtime scope."""
        suite_context = SUITE_EXECUTION_CONTEXT.get()
        scope_context = ScopeContext.for_module(
            suite_execution_id=suite_context.suite_execution_id,
            module_path=self.module_path,
        )
        scope_context.__enter__()
        self._scope_contexts.append(scope_context)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous scope context."""
        self._scope_contexts.pop().__exit__(exc_type, exc, traceback)


@dataclass(slots=True)
class ResourceHookContext:
    """Runtime metadata owned by one resource hook application."""

    consumer_spec: Spec
    provider_spec: ResourceSpec
    direct_dependencies: tuple[ResourceSpec, ...] = ()
    _tokens: list[Token[ResourceHookContext]] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    def __enter__(self) -> ResourceHookContext:
        """Bind this hook metadata to the current hook scope."""
        self._tokens.append(RESOURCE_TRANSACTION_CONTEXT.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous resource hook metadata."""
        RESOURCE_TRANSACTION_CONTEXT.reset(self._tokens.pop())


class SuiteContext(BaseModel):
    """Read-only data resolved before executing one suite."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config = Field(default_factory=Config)
    suite_execution_id: UUID = Field(default_factory=uuid4)
    host: SuiteHost = Field(default_factory=SuiteHost.build_from_current)
    process: CurrentProcessKind = CurrentProcessKind.MAIN
    experiment_variant: Any | None = None
    experiment_setup_chain: tuple[Any, ...] = ()
    _tokens: list[Token[SuiteContext]] = PrivateAttr(default_factory=list)
    _scope_contexts: list[ScopeContext] = PrivateAttr(default_factory=list)

    def __enter__(self) -> SuiteContext:
        """Bind this suite context to the current suite execution scope."""
        self._tokens.append(SUITE_EXECUTION_CONTEXT.set(self))
        scope_context = ScopeContext.for_suite(self.suite_execution_id)
        scope_context.__enter__()
        self._scope_contexts.append(scope_context)
        if self.process is CurrentProcessKind.MAIN:
            EnvironmentStorage().gc_stale()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous suite context."""
        self._scope_contexts.pop().__exit__(exc_type, exc, traceback)
        if self.process is CurrentProcessKind.MAIN:
            EnvironmentStorage.release_suite(self.suite_execution_id)
        SUITE_EXECUTION_CONTEXT.reset(self._tokens.pop())

    def __getstate__(self) -> dict[str, Any]:
        """Serialize suite data without process-local contextvar tokens."""
        state = super().__getstate__()
        state["__pydantic_private__"] = {
            "_scope_contexts": [],
            "_tokens": [],
        }
        return state


TEST_EXECUTION_CONTEXT: ContextVar[TestContext] = ContextVar(
    "test_execution_context"
)
SUITE_EXECUTION_CONTEXT: ContextVar[SuiteContext] = ContextVar(
    "suite_execution_context"
)
AVAILABLE_TEST_TRACER: ContextVar[TestTracer | None] = ContextVar(
    "available_test_tracer", default=None
)
SUT_SPAN_IDS: ContextVar[tuple[int, ...]] = ContextVar(
    "sut_span_ids", default=()
)
RESOURCE_TRANSACTION_CONTEXT: ContextVar[ResourceHookContext] = ContextVar(
    "resource_transaction_context",
)


@contextmanager
def bind[T](var: ContextVar[T], value: T) -> Iterator[None]:
    """Bind a context variable for a scoped block."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)
