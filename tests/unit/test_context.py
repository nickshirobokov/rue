import asyncio
from uuid import uuid4

import pytest

from rue import metrics
from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.collectors import (
    CURRENT_ASSERTION_RESULTS,
)
from rue.context.runtime import (
    CURRENT_TEST,
    TestContext as Ctx,
    bind,
)
from rue.models import Locator
from rue.resources import ResourceSpec, Scope, registry
from rue.resources.metrics.base import Metric, MetricMetadata
from rue.testing.models import LoadedTestDef
from tests.unit.factories import make_definition, make_run_context


def _make_item(
    name: str = "test_fn",
    suffix: str | None = None,
    case_id=None,
) -> LoadedTestDef:
    """Create a minimal LoadedTestDef for testing."""
    return make_definition(
        name=name, module_path="test.py", suffix=suffix, case_id=case_id
    )


def _ctx(name: str = "test_fn") -> Ctx:
    make_run_context(db_enabled=False)
    return Ctx(item=_make_item(name), execution_id=uuid4())


@pytest.fixture(autouse=True)
def clean_registry():
    """Avoid cross-test leakage of globally-registered metric resources."""
    registry.reset()
    yield
    registry.reset()


def test_assertionresult_appends_to_test_context():
    assertion_results: list[AssertionResult] = []

    with _ctx(), bind(CURRENT_ASSERTION_RESULTS, assertion_results):
        ar = AssertionResult(
            passed=True,
            expression_repr=AssertionRepr(
                expr="x == y",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
        )

    assert assertion_results == [ar]

    # Outside the scope, assertion results should not be auto-attached.
    with _ctx():
        ar2 = AssertionResult(
            passed=True,
            expression_repr=AssertionRepr(
                expr="a == b",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
        )
    assert assertion_results == [ar]
    assert ar2 not in assertion_results


def test_metrics_records_assertion_passed_without_test_context_metadata():
    test_ctx = _ctx("my_merit")

    m1 = Metric(
        metadata=MetricMetadata(
            identity=ResourceSpec(
                locator=Locator(module_path=None, function_name="m1"),
                scope=Scope.RUN,
            )
        )
    )
    m2 = Metric(
        metadata=MetricMetadata(
            identity=ResourceSpec(
                locator=Locator(module_path=None, function_name="m2"),
                scope=Scope.RUN,
            )
        )
    )

    with test_ctx, metrics(m1, m2):
        # AssertionResult.__post_init__ calls metric.add_record(self.passed)
        AssertionResult(
            passed=True,
            expression_repr=AssertionRepr(
                expr="first",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
        )
        AssertionResult(
            passed=False,
            expression_repr=AssertionRepr(
                expr="second",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
        )

    assert m1.raw_values == [True, False]
    assert m2.raw_values == [True, False]

    # add_record no longer records consumers; metric resources get them from
    # resolver injection hooks.
    assert m1.metadata.consumers == []
    assert m2.metadata.consumers == []


def test_bind_restores_previous_value():
    outer = _ctx("outer")
    inner = _ctx("inner")

    with outer:
        assert CURRENT_TEST.get().item.spec.locator.function_name == "outer"
        with inner:
            assert (
                CURRENT_TEST.get().item.spec.locator.function_name == "inner"
            )
        assert CURRENT_TEST.get().item.spec.locator.function_name == "outer"

    with pytest.raises(LookupError):
        CURRENT_TEST.get()


@pytest.mark.asyncio
async def test_bind_isolates_values_between_tasks():
    async def read_value(name: str) -> str:
        with _ctx(name):
            await asyncio.sleep(0)
            return CURRENT_TEST.get().item.spec.locator.function_name

    values = await asyncio.gather(read_value("left"), read_value("right"))

    assert values == ["left", "right"]
    with pytest.raises(LookupError):
        CURRENT_TEST.get()
