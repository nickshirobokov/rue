import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from rue import metrics
from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.collectors import (
    CURRENT_ASSERTION_RESULTS,
    CURRENT_PREDICATE_RESULTS,
)
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_TEST,
    TestContext as Ctx,
    bind,
)
from rue.metrics_.base import Metric, metric
from rue.predicates.models import PredicateResult
from rue.resources import ResourceResolver, Scope, registry
from rue.testing.discovery import TestItem


def _make_item(
    name: str = "test_fn",
    suffix: str | None = None,
    case_id=None,
) -> TestItem:
    """Create a minimal TestItem for testing."""
    return TestItem(
        name=name,
        fn=lambda: None,
        module_path=Path("test.py"),
        is_async=False,
        suffix=suffix,
        case_id=case_id,
    )


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


def test_assertion_context_collects_recorded_predicate_results():
    test_ctx = Ctx(item=_make_item("test_name"))

    # Collect predicate results into a list
    predicate_results_list: list[PredicateResult] = []

    with (
        bind(CURRENT_TEST, test_ctx),
        bind(CURRENT_PREDICATE_RESULTS, predicate_results_list),
    ):
        pr = PredicateResult(
            actual="a",
            reference="b",
            name="manual_predicate",
            strict=True,
            value=True,
        )
        assert pr.value is True
        assert predicate_results_list == []

        c = CURRENT_PREDICATE_RESULTS.get()
        assert c is not None
        c.append(pr)

    # Build AssertionResult with collected data
    ar = AssertionResult(
        passed=True,
        expression_repr=AssertionRepr(
            expr="check",
            lines_above="",
            lines_below="",
            resolved_args={},
        ),
        predicate_results=predicate_results_list,
    )

    assert len(ar.predicate_results) == 1
    assert ar.predicate_results[0] == pr


def test_metrics_records_assertion_passed_and_reads_test_context_for_metadata():
    test_ctx = Ctx(item=_make_item("my_merit"))

    m1 = Metric(name="m1")
    m2 = Metric(name="m2")

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


@pytest.mark.asyncio
async def test_metric_injection_reads_resolver_context():
    @metric(scope=Scope.CASE)
    def injected_metric() -> Generator[Metric, Any, Any]:
        yield Metric(name="ignored_by_on_resolve")

    resolver = ResourceResolver(registry)
    with bind(CURRENT_RESOURCE_CONSUMER, "consumer_a"):
        m = await resolver.resolve("injected_metric")

    assert "consumer_a" in m.metadata.collected_from_resources


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
