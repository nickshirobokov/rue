import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from rue import metrics
from rue.assertions.base import AssertionRepr, AssertionResult
from rue.context.collectors import (
    CURRENT_ASSERTION_RESULTS,
)
from rue.context.process_pool import CURRENT_PROCESS_POOL, LazyProcessPool
from rue.context.runtime import (
    CURRENT_TEST,
    TestContext as Ctx,
    bind,
)
from rue.context.scopes import ScopeContext, ScopeOwner
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


def test_scope_context_for_run_resolves_only_run_owner():
    run_id = uuid4()

    with ScopeContext.for_run(run_id):
        assert ScopeContext.current_owner(Scope.RUN) == ScopeOwner(
            scope=Scope.RUN,
            run_id=run_id,
        )
        with pytest.raises(RuntimeError, match="open TestContext"):
            ScopeContext.current_owner(Scope.TEST)
        with pytest.raises(RuntimeError, match="open TestContext"):
            ScopeContext.current_owner(Scope.MODULE)


def test_scope_models_resource_provider_policy():
    assert Scope.provider_priority() == (Scope.TEST, Scope.MODULE, Scope.RUN)
    assert Scope.TEST.dependency_scopes == frozenset(
        {Scope.TEST, Scope.MODULE, Scope.RUN}
    )
    assert Scope.MODULE.dependency_scopes == frozenset(
        {Scope.MODULE, Scope.RUN}
    )
    assert Scope.RUN.dependency_scopes == frozenset({Scope.RUN})


def test_scope_context_for_test_resolves_all_scope_owners():
    run_id = uuid4()
    execution_id = uuid4()
    module_path = Path("test_module.py")

    with ScopeContext.for_test(run_id, execution_id, module_path):
        assert ScopeContext.current_owner(Scope.RUN) == ScopeOwner(
            scope=Scope.RUN,
            run_id=run_id,
        )
        assert ScopeContext.current_owner(Scope.TEST) == ScopeOwner(
            scope=Scope.TEST,
            execution_id=execution_id,
            run_id=run_id,
        )
        assert ScopeContext.current_owner(Scope.MODULE) == ScopeOwner(
            scope=Scope.MODULE,
            run_id=run_id,
            module_path=module_path.resolve(),
        )


def test_scope_context_restores_nested_owner_sets():
    outer_run_id = uuid4()
    inner_run_id = uuid4()

    with ScopeContext.for_run(outer_run_id):
        assert ScopeContext.current_owner(Scope.RUN).run_id == outer_run_id
        with ScopeContext.for_run(inner_run_id):
            assert ScopeContext.current_owner(Scope.RUN).run_id == inner_run_id
        assert ScopeContext.current_owner(Scope.RUN).run_id == outer_run_id


def test_scope_context_supports_arbitrary_callers_without_runtime_contexts():
    run_id = uuid4()
    execution_id = uuid4()

    with ScopeContext.for_test(run_id, execution_id, Path("direct.py")):
        assert ScopeContext.current_owner(Scope.TEST).execution_id == (
            execution_id
        )


def test_lazy_process_pool_binds_current_holder_and_shutdowns_on_exit(
    monkeypatch,
):
    shutdown_calls = 0

    class FakeExecutor:
        def shutdown(self, *, wait):
            nonlocal shutdown_calls
            assert wait is True
            shutdown_calls += 1

    monkeypatch.setattr(
        "rue.context.process_pool.ProcessPoolExecutor",
        lambda **_kwargs: FakeExecutor(),
    )

    with LazyProcessPool(max_workers=2) as pool:
        assert LazyProcessPool.current() is pool
        assert LazyProcessPool.current_executor() is pool.get()

    assert shutdown_calls == 1
    assert CURRENT_PROCESS_POOL.get() is None


def test_lazy_process_pool_requires_active_context():
    with pytest.raises(RuntimeError, match="No active process pool scope"):
        LazyProcessPool.current_executor()
