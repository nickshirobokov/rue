"""Runtime context variables for Rue execution."""

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
from rue.context.models import RunEnvironment
from rue.context.scopes import ScopeContext
from rue.models import Spec


if TYPE_CHECKING:
    from rue.resources.models import ResourceSpec
    from rue.testing.models.loaded import LoadedTestDef
    from rue.testing.tracing import TestTracer


@dataclass(slots=True)
class TestContext:
    """Runtime data owned by one executing test."""

    __test__ = False

    item: LoadedTestDef
    execution_id: UUID
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
        """Bind this test context to the current execution scope."""
        self._tokens.append(CURRENT_TEST.set(self))
        run_context = CURRENT_RUN_CONTEXT.get()
        scope_context = ScopeContext.for_test(
            run_id=run_context.run_id,
            execution_id=self.execution_id,
            module_path=self.module_path,
        )
        scope_context.__enter__()
        self._scope_contexts.append(scope_context)
        return self

    @property
    def module_path(self) -> Path:
        """Return the resolved module path for this test context."""
        return (
            self.item.spec.locator.module_path or Path("<dynamic>")
        ).resolve()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous test context."""
        self._scope_contexts.pop().__exit__(exc_type, exc, traceback)
        CURRENT_TEST.reset(self._tokens.pop())


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
        self._tokens.append(CURRENT_RESOURCE_HOOK_CONTEXT.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous resource hook metadata."""
        CURRENT_RESOURCE_HOOK_CONTEXT.reset(self._tokens.pop())


class RunContext(BaseModel):
    """Read-only data resolved before executing one run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config = Field(default_factory=Config)
    run_id: UUID = Field(default_factory=uuid4)
    environment: RunEnvironment = Field(
        default_factory=RunEnvironment.build_from_current
    )
    experiment_variant: Any | None = None
    experiment_setup_chain: tuple[Any, ...] = ()
    _tokens: list[Token[RunContext]] = PrivateAttr(default_factory=list)
    _scope_contexts: list[ScopeContext] = PrivateAttr(default_factory=list)

    def __enter__(self) -> RunContext:
        """Bind this run context to the current execution scope."""
        self._tokens.append(CURRENT_RUN_CONTEXT.set(self))
        scope_context = ScopeContext.for_run(self.run_id)
        scope_context.__enter__()
        self._scope_contexts.append(scope_context)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous run context."""
        self._scope_contexts.pop().__exit__(exc_type, exc, traceback)
        CURRENT_RUN_CONTEXT.reset(self._tokens.pop())

    def __getstate__(self) -> dict[str, Any]:
        """Serialize run data without process-local contextvar tokens."""
        state = super().__getstate__()
        state["__pydantic_private__"] = {
            "_scope_contexts": [],
            "_tokens": [],
        }
        return state


CURRENT_TEST: ContextVar[TestContext] = ContextVar("current_test")
CURRENT_RUN_CONTEXT: ContextVar[RunContext] = ContextVar(
    "current_run_context"
)
CURRENT_TEST_TRACER: ContextVar[TestTracer | None] = ContextVar(
    "current_test_tracer", default=None
)
CURRENT_SUT_SPAN_IDS: ContextVar[tuple[int, ...]] = ContextVar(
    "current_sut_span_ids", default=()
)
CURRENT_RESOURCE_HOOK_CONTEXT: ContextVar[
    ResourceHookContext
] = ContextVar(
    "current_resource_hook_context",
)


@contextmanager
def bind[T](var: ContextVar[T], value: T) -> Iterator[None]:
    """Bind a context variable for a scoped block."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)
