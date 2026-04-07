from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar
from uuid import UUID


if TYPE_CHECKING:
    from rue.testing.models import TestDefinition
    from rue.testing.runner import Runner
    from rue.testing.tracing import TestTracer


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TestContext:
    __test__ = False

    item: TestDefinition
    execution_id: UUID | None = None


CURRENT_TEST: ContextVar[TestContext | None] = ContextVar(
    "current_test", default=None
)
CURRENT_TEST_TRACER: ContextVar[TestTracer | None] = ContextVar(
    "current_test_tracer", default=None
)
CURRENT_SUT_SPAN_IDS: ContextVar[tuple[int, ...]] = ContextVar(
    "current_sut_span_ids", default=()
)
CURRENT_RUNNER: ContextVar[Runner | None] = ContextVar(
    "current_runner", default=None
)
CURRENT_RESOURCE_CONSUMER: ContextVar[str | None] = ContextVar(
    "current_resource_consumer", default=None
)


@contextmanager
def bind(var: ContextVar[T], value: T) -> Iterator[None]:
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)
