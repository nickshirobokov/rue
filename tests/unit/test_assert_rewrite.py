import sys
from uuid import uuid4

import pytest

from rue import metrics as metrics_scope_ctx
from rue.assertions.base import AssertionResult
from rue.context.collectors import (
    CURRENT_ASSERTION_RESULTS,
    CURRENT_METRIC_RESULTS,
)
from rue.context.runtime import TestContext, bind
from rue.models import Locator
from rue.resources import ResourceResolver, ResourceSpec, Scope, registry
from rue.resources.metrics.base import Metric, MetricMetadata, MetricResult
from tests.unit.factories import make_run_context, materialize_tests


def test_rewritten_assert_collects_predicate_results(tmp_path):
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(
        """
from rue import test
from rue.models import Locator
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import Metric, MetricMetadata
from rue.predicates import predicate

@predicate
def equals(actual, reference):
    return actual == reference

@test
def test_sample():
    m = Metric(metadata=MetricMetadata(identity=ResourceSpec(locator=Locator(module_path=None, function_name="m"), scope=Scope.RUN)))
    m.add_record([1, 2, 3])
    assert equals(1, 1) and (m.len == 3)
""".lstrip()
    )

    try:
        [item] = materialize_tests(mod_path)
        assertion_results: list[AssertionResult] = []
        make_run_context()
        ctx = TestContext(item=item, execution_id=uuid4())
        with (
            ctx,
            bind(CURRENT_ASSERTION_RESULTS, assertion_results),
        ):
            item.fn()

        assert len(assertion_results) == 1
        ar = assertion_results[0]
        assert ar.passed is True
        assert "equals(1, 1)" in ar.expression_repr.expr

        assert len(ar.predicate_results) == 1
        assert ar.predicate_results[0].name == "equals"

    finally:
        sys.modules.pop(mod_name, None)


def test_rewritten_assert_failure_sets_error_message_and_raises(tmp_path):
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(
        """
from rue import test
from rue.predicates import predicate

@predicate
def equals(actual, reference):
    return actual == reference

@test
def test_fail():
    assert equals(1, 2), "nope"
""".lstrip()
    )

    try:
        [item] = materialize_tests(mod_path)
        assertion_results: list[AssertionResult] = []
        make_run_context()
        ctx = TestContext(item=item, execution_id=uuid4())
        with (
            ctx,
            bind(CURRENT_ASSERTION_RESULTS, assertion_results),
        ):
            item.fn()

        assert len(assertion_results) == 1
        ar = assertion_results[0]
        assert ar.passed is False
        assert ar.error_message == "nope"
        assert "equals(1, 2)" in ar.expression_repr.expr
    finally:
        sys.modules.pop(mod_name, None)


def test_rewritten_multiple_asserts_record_multiple_metric_values(tmp_path):
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(
        """
from rue import test
from rue.predicates import predicate

@predicate
def equals(actual, reference):
    return actual == reference

@test
def test_metric_capture_multi():
    assert equals(1, 1)
    assert equals(1, 2), "nope"
""".lstrip()
    )

    try:
        [item] = materialize_tests(mod_path)
        assertion_results: list[AssertionResult] = []
        make_run_context()
        ctx = TestContext(item=item, execution_id=uuid4())
        m = Metric(
            metadata=MetricMetadata(
                identity=ResourceSpec(
                    locator=Locator(
                        module_path=None,
                        function_name="assert_outcomes",
                    ),
                    scope=Scope.RUN,
                )
            )
        )
        with (
            ctx,
            metrics_scope_ctx(m),
            bind(CURRENT_ASSERTION_RESULTS, assertion_results),
        ):
            item.fn()

        assert m.raw_values == [True, False]
        assert m.metadata.consumers == []
        assert len(assertion_results) == 2
        assert assertion_results[0].passed is True
        assert assertion_results[1].passed is False
    finally:
        sys.modules.pop(mod_name, None)


@pytest.mark.asyncio
async def test_rewritten_asserts_inside_metric_functions_are_collected(
    tmp_path,
):
    registry.reset()
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(
        """
import rue
from rue.models import Locator
from rue.resources import ResourceSpec, Scope
from rue.resources.metrics.base import Metric, MetricMetadata

@rue.resource.metric
def my_metric():
    m = Metric(metadata=MetricMetadata(identity=ResourceSpec(locator=Locator(module_path=None, function_name="m"), scope=Scope.RUN)))
    yield m
    assert False, "nope"

@rue.test
def test_dummy():
    pass
""".lstrip()
    )

    try:
        [item] = materialize_tests(mod_path)
        resolver = ResourceResolver(registry)
        ctx = TestContext(item=item, execution_id=uuid4())
        metric_results: list[MetricResult] = []
        with ctx, bind(CURRENT_METRIC_RESULTS, metric_results):
            graph = registry.compile_graph(
                {"test": (item.spec, ("my_metric",))}
            )
            await resolver.resolve_resource(
                graph.injections_by_key["test"]["my_metric"],
                consumer_spec=item.spec,
            )
            await resolver.teardown()

        assert len(metric_results) == 1
        [metric_result] = metric_results
        assert len(metric_result.assertion_results) == 1
        ar = metric_result.assertion_results[0]
        assert ar.passed is False
        assert ar.error_message == "nope"
    finally:
        registry.reset()
        sys.modules.pop(mod_name, None)


def test_assertion_repr_major_cases(tmp_path):
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(
        """
from rue import test

@test
def test_repr_cases():
    t1 = 5
    t2 = 10
    print(t1)
    print(t2)
    assert t1
    print("hello")
    print("world")
    class Obj:
        def __init__(self):
            self.attr = 7
    obj = Obj()
    assert obj.attr
    arr = [1, 2, 3]
    assert arr[0]
    def func(x):
        return x + 1
    assert func(4)
    xs = [0, 1, 2]
    assert [x > 0 for x in xs]
""".lstrip()
    )

    try:
        [item] = materialize_tests(mod_path)
        assertion_results: list[AssertionResult] = []
        with TestContext(item=item, execution_id=uuid4()), bind(
            CURRENT_ASSERTION_RESULTS,
            assertion_results,
        ):
            item.fn()

        assert len(assertion_results) == 5
        results = {
            ar.expression_repr.expr: ar.expression_repr
            for ar in assertion_results
        }

        t1_repr = results["assert t1"]
        assert t1_repr.lines_above == "\n    print(t1)\n    print(t2)"
        assert t1_repr.lines_below == '\n    print("hello")\n    print("world")'
        assert t1_repr.resolved_args == {"t1": "5"}

        assert results["assert obj.attr"].resolved_args == {"obj.attr": "7"}
        assert results["assert arr[0]"].resolved_args == {"arr[0]": "1"}
        assert results["assert func(4)"].resolved_args == {"func(4)": "5"}
        assert results["assert [x > 0 for x in xs]"].resolved_args == {
            "[x > 0 for x in xs]": "[False, True, True]"
        }
    finally:
        sys.modules.pop(mod_name, None)


def test_assertion_repr_multiline_assert(tmp_path):
    mod_name = f"test_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(
        """
from rue import test

@test
def test_multiline_assert():
    def func(x):
        return x + 1
    x = 4
    print("above")
    assert func(
        x
    )
    print("below")
""".lstrip()
    )

    try:
        [item] = materialize_tests(mod_path)
        assertion_results: list[AssertionResult] = []
        with TestContext(item=item, execution_id=uuid4()), bind(
            CURRENT_ASSERTION_RESULTS,
            assertion_results,
        ):
            item.fn()

        assert len(assertion_results) == 1
        [ar] = assertion_results

        assert ar.expression_repr.expr == "assert func(\n        x\n    )"
        assert (
            ar.expression_repr.lines_above == '\n    x = 4\n    print("above")'
        )
        assert ar.expression_repr.lines_below == '\n    print("below")'
        assert ar.expression_repr.resolved_args == {
            "func(\n        x\n    )": "5"
        }
    finally:
        sys.modules.pop(mod_name, None)
