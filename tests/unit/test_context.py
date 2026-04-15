import asyncio
from pathlib import Path

import pytest

from rue import metrics
from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.collectors import (
    CURRENT_ASSERTION_RESULTS,
)
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_TEST,
    TestContext as Ctx,
    bind,
)
from rue.resources import ResourceIdentity, Scope, registry
from rue.resources.metrics.base import Metric, MetricMetadata
from rue.testing.models import TestDefinition
from tests.unit.factories import make_definition


def _make_item(
    name: str = "test_fn",
    suffix: str | None = None,
    case_id=None,
) -> TestDefinition:
    """Create a minimal TestDefinition for testing."""
    return make_definition(name=name, module_path="test.py", suffix=suffix, case_id=case_id)


@pytest.fixture(autouse=True)
def clean_registry():
    """Avoid cross-test leakage of globally-registered metric resources."""
    registry.reset()
    yield
    registry.reset()


def test_assertionresult_appends_to_test_context():
    assertion_results: list[AssertionResult] = []

    with bind(CURRENT_ASSERTION_RESULTS, assertion_results):
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


def test_metrics_records_assertion_passed_and_reads_test_context_for_metadata():
    test_ctx = Ctx(item=_make_item("my_merit"))

    m1 = Metric(
        metadata=MetricMetadata(
            identity=ResourceIdentity(name="m1", scope=Scope.SESSION)
        )
    )
    m2 = Metric(
        metadata=MetricMetadata(
            identity=ResourceIdentity(name="m2", scope=Scope.SESSION)
        )
    )

    with bind(CURRENT_TEST, test_ctx), metrics(m1, m2):
        # AssertionResult.__post_init__ calls metric.add_record(self.passed)
        ar1 = AssertionResult(
            passed=True,
            expression_repr=AssertionRepr(
                expr="first",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
        )
        ar2 = AssertionResult(
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

    # add_record is called from AssertionResult.__post_init__, so attribution should be captured.
    assert "my_merit" in m1.metadata.collected_from_tests


def test_bind_restores_previous_value():
    assert CURRENT_RESOURCE_CONSUMER.get() is None

    with bind(CURRENT_RESOURCE_CONSUMER, "outer"):
        assert CURRENT_RESOURCE_CONSUMER.get() == "outer"
        with bind(CURRENT_RESOURCE_CONSUMER, "inner"):
            assert CURRENT_RESOURCE_CONSUMER.get() == "inner"
        assert CURRENT_RESOURCE_CONSUMER.get() == "outer"

    assert CURRENT_RESOURCE_CONSUMER.get() is None


@pytest.mark.asyncio
async def test_bind_isolates_values_between_tasks():
    async def read_value(name: str) -> str | None:
        with bind(CURRENT_RESOURCE_CONSUMER, name):
            await asyncio.sleep(0)
            return CURRENT_RESOURCE_CONSUMER.get()

    values = await asyncio.gather(read_value("left"), read_value("right"))

    assert values == ["left", "right"]
    assert CURRENT_RESOURCE_CONSUMER.get() is None
