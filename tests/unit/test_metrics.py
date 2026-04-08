import math
import statistics
import warnings
from pathlib import Path
from uuid import UUID

import pytest

from rue import metrics
from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_TEST,
    TestContext as Ctx,
    bind,
)
from rue.resources import ResourceResolver, Scope, registry
from rue.resources.metrics.base import Metric, MetricMetadata, MetricResult, metric
from rue.testing.discovery import TestItem


def _make_item(
    name: str = "test_fn",
    suffix: str | None = None,
    case_id: UUID | None = None,
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


def test_metric_computations():
    """Test statistical property computations."""
    m = Metric("test_stats")
    m.add_record([10, 20, 30, 40, 50])

    assert m.sum == 150.0
    assert m.min == 10.0
    assert m.max == 50.0
    assert m.mean == 30.0
    assert m.median == 30.0
    assert m.variance == 250.0
    assert math.isclose(m.std, statistics.stdev([10, 20, 30, 40, 50]))
    assert m.pvariance == 200.0  # (400 + 100 + 0 + 100 + 400) / 5
    assert math.isclose(m.pstd, statistics.pstdev([10, 20, 30, 40, 50]))


def test_metric_records_case_id_before_suffix():
    m = Metric("test_case_id")
    test_ctx = Ctx(
        item=_make_item(
            "test_case",
            suffix="{'slug': 'example'}",
            case_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
    )

    with bind(CURRENT_TEST, test_ctx):
        m.add_record(1)

    assert m.metadata.collected_from_cases == {
        "00000000-0000-0000-0000-000000000001"
    }


def test_metric_records_suffix_when_case_id_missing():
    m = Metric("test_case_suffix")
    test_ctx = Ctx(item=_make_item("test_case", suffix="{'slug': 'example'}"))

    with bind(CURRENT_TEST, test_ctx):
        m.add_record(1)

    assert m.metadata.collected_from_cases == {"{'slug': 'example'}"}


def test_metric_empty_edge_cases_do_not_crash():
    m = Metric("empty")
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Cannot compute .* - not enough values. Returning NaN.",
            category=UserWarning,
        )
        assert math.isnan(m.pvariance)
        assert math.isnan(m.pstd)

        ci90 = m.ci_90
        ci95 = m.ci_95
        ci99 = m.ci_99
        assert math.isnan(ci90[0]) and math.isnan(ci90[1])
        assert math.isnan(ci95[0]) and math.isnan(ci95[1])
        assert math.isnan(ci99[0]) and math.isnan(ci99[1])


def test_metric_result_is_collected_when_collector_is_active():
    results = []
    with bind(CURRENT_METRIC_RESULTS, results):
        MetricResult(
            name="x",
            metadata=MetricMetadata(),
            assertion_results=[],
            value=1,
        )
    assert len(results) == 1
    assert results[0].name == "x"


def test_metrics_context_accepts_legacy_list_argument():
    m = Metric("acc")

    with metrics([m]):  # type: ignore
        AssertionResult(
            expression_repr=AssertionRepr(
                expr="x",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
            passed=True,
        )

    assert m.raw_values == [True]


@pytest.mark.asyncio
async def test_metric_decorator_no_args():
    """Test @metric decorator without explicit arguments."""
    registry.reset()

    @metric
    def default_metric():
        yield Metric("default")
        return 0

    resolver = ResourceResolver(registry)
    m = await resolver.resolve("default_metric")
    assert m.name == "default_metric"


@pytest.mark.asyncio
async def test_metric_on_injection_hook_with_context():
    """Rue/case attribution happens in add_record; resource attribution happens on injection."""
    registry.reset()

    @metric(scope=Scope.CASE)
    def test_ctx_metric():
        yield Metric("ctx")
        return 0

    resolver = ResourceResolver(registry)
    ctx = Ctx(item=_make_item("my_merit"))
    with bind(CURRENT_TEST, ctx):
        with bind(CURRENT_RESOURCE_CONSUMER, "some_resource"):
            m = await resolver.resolve("test_ctx_metric")
            # injection hook attribution
            assert "some_resource" in m.metadata.collected_from_resources
            # test data attribution is delegated to add_record
            assert "my_merit" not in m.metadata.collected_from_tests
            m.add_record(1)

    assert "my_merit" in m.metadata.collected_from_tests
    assert m.metadata.scope == Scope.CASE


@pytest.mark.asyncio
async def test_metric_decorator_emits_metric_result_on_teardown_with_assertions_and_return_value():
    registry.reset()

    @metric(scope=Scope.CASE)
    def scored_metric():
        AssertionResult(
            expression_repr=AssertionRepr(
                expr="before",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
            passed=True,
        )
        yield Metric("ignored")
        AssertionResult(
            expression_repr=AssertionRepr(
                expr="after",
                lines_above="",
                lines_below="",
                resolved_args={},
            ),
            passed=False,
        )
        yield 123
        return 999  # ignored: metric final value comes from the second yield

    resolver = ResourceResolver(registry)
    metric_results = []
    with bind(CURRENT_METRIC_RESULTS, metric_results):
        m = await resolver.resolve("scored_metric")
        assert m.name == "scored_metric"
        await resolver.teardown()

    assert len(metric_results) == 1
    r = metric_results[0]
    assert r.name == "scored_metric"
    assert r.value == 123
    assert [a.expression_repr.expr for a in r.assertion_results] == [
        "before",
        "after",
    ]
    assert r.metadata.scope == Scope.CASE
    assert r.metadata is not m.metadata
