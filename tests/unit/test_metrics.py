import math
import statistics
import warnings
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from rue import metrics
from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.runtime import (
    TestContext as Ctx,
    bind,
)
from rue.models import Locator
from rue.resources import ResourceResolver, ResourceSpec, Scope, registry
from rue.resources.metrics.base import Metric, MetricMetadata, MetricResult
from rue.resources.metrics.decorator import metric
from rue.testing.models import LoadedTestDef
from tests.unit.factories import make_definition, make_run_context


_TEST_GRAPH_KEY = UUID(int=1)


def _metric(name: str = "") -> Metric:
    return Metric(
        metadata=MetricMetadata(
            identity=ResourceSpec(
                locator=Locator(module_path=None, function_name=name),
                scope=Scope.RUN,
            )
        )
    )


def _make_item(
    name: str = "test_fn",
    module_path: Path | None = None,
    suffix: str | None = None,
    case_id: UUID | None = None,
) -> LoadedTestDef:
    """Create a minimal LoadedTestDef for testing."""
    return make_definition(
        name,
        module_path=module_path or Path("test.py"),
        suffix=suffix,
        case_id=case_id,
    )


def _consumer_spec(
    name: str = "test_fn",
    *,
    module_path: Path | None = None,
):
    return _make_item(name=name, module_path=module_path).spec


async def _resolve(
    resolver: ResourceResolver,
    name: str,
    *,
    consumer_spec=None,
    apply_injection_hook: bool = True,
):
    consumer = consumer_spec or _consumer_spec()
    graph = resolver.registry.compile_di_graph(
        {_TEST_GRAPH_KEY: (consumer, (name,))}
    )
    return await resolver.resolve_resource(
        graph.injections_by_execution_id[_TEST_GRAPH_KEY][name],
        consumer_spec=consumer,
        apply_injection_hook=apply_injection_hook,
    )


def _resource_spec(name: str, *, consumer_spec=None) -> ResourceSpec:
    consumer = consumer_spec or _consumer_spec()
    graph = registry.compile_di_graph({_TEST_GRAPH_KEY: (consumer, (name,))})
    return graph.injections_by_execution_id[_TEST_GRAPH_KEY][name]


def _ctx(
    name: str = "test_fn",
    *,
    module_path: Path | None = None,
    suffix: str | None = None,
    case_id: UUID | None = None,
) -> Ctx:
    make_run_context(db_enabled=False)
    return Ctx(
        item=_make_item(
            name,
            module_path=module_path,
            suffix=suffix,
            case_id=case_id,
        ),
        execution_id=uuid4(),
    )


def test_metric_computations():
    """Test statistical property computations."""
    m = _metric("test_stats")
    with _ctx():
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


def test_metric_add_record_does_not_collect_consumers_from_test_context():
    m = _metric("test_context")
    test_ctx = _ctx("test_case")

    with test_ctx:
        m.add_record(1)

    assert m.metadata.consumers == []


@pytest.mark.asyncio
async def test_metric_on_injection_records_case_id_before_suffix():
    registry.reset()
    m = _metric("test_case_id")
    ctx = _ctx(
        "test_case",
        suffix="{'slug': 'example'}",
        case_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    @metric(scope=Scope.TEST)
    def test_case_metric():
        yield m

    resolver = ResourceResolver(registry)
    with ctx:
        result = await _resolve(
            resolver,
            "test_case_metric",
            consumer_spec=ctx.item.spec,
        )

    assert result.metadata.consumers == [ctx.item.spec]
    assert (
        MetricResult(metadata=result.metadata, assertion_results=[], value=1)
        .primary_case_id
        == "00000000-0000-0000-0000-000000000001"
    )


@pytest.mark.asyncio
async def test_metric_on_injection_records_suffix_when_case_id_missing():
    registry.reset()
    m = _metric("test_case_suffix")
    ctx = _ctx("test_case", suffix="{'slug': 'example'}")

    @metric(scope=Scope.TEST)
    def test_case_suffix_metric():
        yield m

    resolver = ResourceResolver(registry)
    with ctx:
        result = await _resolve(
            resolver,
            "test_case_suffix_metric",
            consumer_spec=ctx.item.spec,
        )

    assert result.metadata.consumers == [ctx.item.spec]
    assert (
        MetricResult(metadata=result.metadata, assertion_results=[], value=1)
        .primary_case_id
        == "{'slug': 'example'}"
    )


def test_metric_empty_edge_cases_do_not_crash():
    m = _metric("empty")
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
        assert math.isnan(ci90[0])
        assert math.isnan(ci90[1])
        assert math.isnan(ci95[0])
        assert math.isnan(ci95[1])
        assert math.isnan(ci99[0])
        assert math.isnan(ci99[1])


def test_metric_result_is_collected_when_collector_is_active():
    results = []
    with bind(CURRENT_METRIC_RESULTS, results):
        MetricResult(
            metadata=MetricMetadata(
                identity=ResourceSpec(
                    locator=Locator(module_path=None, function_name="x"),
                    scope=Scope.RUN,
                )
            ),
            assertion_results=[],
            value=1,
        )
    assert len(results) == 1
    assert results[0].metadata.identity.locator.function_name == "x"


def test_metrics_context_accepts_legacy_list_argument():
    m = _metric("acc")

    with _ctx(), metrics([m]):  # type: ignore
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
        yield _metric("default")
        return 0

    resolver = ResourceResolver(registry)
    m = await _resolve(
        resolver,
        "default_metric",
        consumer_spec=_consumer_spec(),
    )
    assert m.metadata.identity.locator.function_name == "default_metric"


@pytest.mark.asyncio
async def test_metric_on_injection_hook_with_context():
    """Metric consumers are recorded from resolver injection data."""
    registry.reset()

    @metric(scope=Scope.TEST)
    def test_ctx_metric():
        yield _metric("ctx")
        return 0

    resolver = ResourceResolver(registry)
    resource_consumer = _resource_spec("test_ctx_metric")
    ctx = _ctx("my_merit")
    with ctx:
        m = await _resolve(
            resolver,
            "test_ctx_metric",
            consumer_spec=resource_consumer,
        )
        assert m.metadata.consumers == [resource_consumer]
        assert ctx.item.spec not in m.metadata.consumers
        m.add_record(1)

    assert m.metadata.consumers == [resource_consumer]
    assert m.metadata.identity.scope == Scope.TEST


@pytest.mark.asyncio
async def test_metric_decorator_emits_result_with_assertions_and_return():
    registry.reset()

    @metric(scope=Scope.TEST)
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
        yield _metric("ignored")
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
    with _ctx(), bind(
        CURRENT_METRIC_RESULTS, metric_results
    ):
        m = await _resolve(
            resolver,
            "scored_metric",
            consumer_spec=_consumer_spec(),
        )
        assert m.metadata.identity.locator.function_name == "scored_metric"
        await resolver.teardown()

    assert len(metric_results) == 1
    r = metric_results[0]
    assert r.metadata.identity.locator.function_name == "scored_metric"
    assert r.value == 123
    assert [a.expression_repr.expr for a in r.assertion_results] == [
        "before",
        "after",
    ]
    assert r.metadata.identity.scope == Scope.TEST


@pytest.mark.asyncio
async def test_metric_test_injection_records_test_consumer_spec():
    registry.reset()

    @metric(scope=Scope.TEST)
    def sampled_metric():
        yield _metric("sampled")

    resolver = ResourceResolver(registry)
    ctx = _ctx("test_metric")
    with ctx:
        m = await _resolve(
            resolver,
            "sampled_metric",
            consumer_spec=ctx.item.spec,
        )

    assert m.metadata.consumers == [ctx.item.spec]
    assert not any(
        isinstance(consumer, ResourceSpec)
        for consumer in m.metadata.consumers
    )


@pytest.mark.asyncio
async def test_metric_resolve_without_injection_hook_skips_consumer_metadata():
    registry.reset()

    @metric(scope=Scope.TEST)
    def sampled_metric():
        yield _metric("sampled")

    resolver = ResourceResolver(registry)
    ctx = _ctx("test_metric")
    with ctx:
        m = await _resolve(
            resolver,
            "sampled_metric",
            consumer_spec=ctx.item.spec,
            apply_injection_hook=False,
        )
        assert m.metadata.consumers == []

        m = await _resolve(
            resolver,
            "sampled_metric",
            consumer_spec=ctx.item.spec,
        )

    assert m.metadata.consumers == [ctx.item.spec]


@pytest.mark.asyncio
async def test_metric_records_module_and_provider_identity():
    registry.reset()

    @metric(scope=Scope.TEST)
    def module_metric():
        metric_instance = _metric("ignored")
        yield metric_instance
        yield metric_instance.mean

    resolver = ResourceResolver(registry)
    metric_results = []
    ctx = _ctx(
        "test_metric",
        module_path=Path("tests/rue_metrics_console.py"),
    )
    with bind(CURRENT_METRIC_RESULTS, metric_results):
        with ctx:
            m = await _resolve(
                resolver,
                "module_metric",
                consumer_spec=ctx.item.spec,
            )
            m.add_record(1)
            await resolver.teardown(Scope.TEST)

    [result] = metric_results
    assert result.metadata.consumers == [ctx.item.spec]
    assert result.metadata.identity.locator.module_path is not None
    assert result.metadata.identity.locator.module_path.parent is not None
    assert result.metadata.identity.locator.function_name == "module_metric"
    assert result.metadata.identity.scope == Scope.TEST


@pytest.mark.asyncio
async def test_metric_decorator_records_metric_dependencies():
    registry.reset()

    @registry.register_resource
    def clock():
        return "utc"

    @metric
    def overall_quality():
        yield _metric("overall")

    @metric
    def accuracy(overall_quality: Metric, clock: str):
        metric_instance = _metric("accuracy")
        yield metric_instance
        yield metric_instance.mean

    resolver = ResourceResolver(registry)
    metric_results = []
    with _ctx(), bind(
        CURRENT_METRIC_RESULTS, metric_results
    ):
        await _resolve(resolver, "accuracy", consumer_spec=_consumer_spec())
        await resolver.teardown()

    by_name = {
        result.metadata.identity.locator.function_name: result
        for result in metric_results
    }
    assert "accuracy" in by_name
    clock_spec = _resource_spec("clock")
    assert by_name["accuracy"].dependencies == [
        by_name["overall_quality"].metadata.identity,
        clock_spec,
    ]
    assert by_name["accuracy"].metadata.direct_providers == [
        by_name["overall_quality"].metadata.identity,
        clock_spec,
    ]
