import os
from pathlib import Path
from textwrap import dedent

import pytest

from rue.resources import DependencyResolver, registry
from rue.testing.execution.suite.executable import ExecutableSuite
from rue.testing.execution.test.models import TestStatus
from tests.helpers import make_suite_context, materialize_tests


def _failures(suite):
    return [
        (
            execution.definition.spec.name,
            execution.result.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in suite.result.test_executions
        if execution.result.status is not TestStatus.PASSED
    ]


async def _suite_module(
    module_path: Path,
    *,
    concurrency: int = 4,
    otel: bool = False,
):
    context = make_suite_context(otel=otel, concurrency=concurrency)
    return await ExecutableSuite(
        items=materialize_tests(module_path),
        suite_execution_id=context.suite_execution_id,
        resolver=DependencyResolver(registry),
    ).execute()


@pytest.mark.asyncio
async def test_subprocess_normal_resource_mutations_do_not_merge_to_parent(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_resource_isolation.py"
    module_path.write_text(
        dedent(
            """
            import time

            import rue
            from rue import ExecutionBackend
            from rue.resources import resource
            from rue.resources.models import Scope


            @resource(scope=Scope.SUITE)
            def shared_events():
                return []


            @rue.test.backend("subprocess")
            @rue.test.iterate.params("event", [("one",), ("two",)])
            def test_remote(event, shared_events):
                time.sleep(0.05)
                shared_events.append(event)


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after(shared_events):
                assert shared_events == []
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=4)

    assert suite.result.passed == 2, _failures(suite)


@pytest.mark.asyncio
async def test_subprocess_normal_generator_resources_run_worker_teardown(
    tmp_path: Path,
):
    teardown_path = tmp_path / "teardown.txt"
    module_path = tmp_path / "test_remote_generator_teardown.py"
    module_path.write_text(
        dedent(
            f"""
            from pathlib import Path

            import rue
            from rue import ExecutionBackend


            TEARDOWN_PATH = Path({str(teardown_path)!r})


            @rue.resource
            def worker_resource():
                yield "ready"
                TEARDOWN_PATH.write_text("closed")


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(worker_resource):
                assert worker_resource == "ready"


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert TEARDOWN_PATH.read_text() == "closed"
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 2, _failures(suite)


@pytest.mark.asyncio
async def test_subprocess_normal_resource_does_not_create_parent_cache(
    tmp_path: Path,
):
    resolved_by_path = tmp_path / "resolved_by.txt"
    module_path = tmp_path / "test_remote_parent_cache.py"
    module_path.write_text(
        dedent(
            f"""
            import os
            from pathlib import Path

            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            RESOLVED_BY_PATH = Path({str(resolved_by_path)!r})


            @rue.resource(scope=Scope.SUITE)
            def suite_value():
                with RESOLVED_BY_PATH.open("a") as file:
                    file.write(f"{{os.getpid()}}\\n")
                return "value"


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(suite_value):
                assert suite_value == "value"


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert str(os.getpid()) not in RESOLVED_BY_PATH.read_text()
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 2, _failures(suite)


@pytest.mark.asyncio
async def test_suite_metric_aggregates_local_and_subprocess_records(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_metric_merge.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            @rue.resource.metric(scope=Scope.SUITE)
            def quality():
                metric = rue.Metric()
                yield metric
                yield metric.sum


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_local(quality):
                quality.add_record(1)


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(quality):
                quality.add_record(2)
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 2, _failures(suite)
    [metric_result] = suite.result.metric_results
    assert metric_result.value == 3


@pytest.mark.asyncio
async def test_concurrent_subprocess_metric_updates_do_not_duplicate_baseline(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_metric_conflicts.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            @rue.resource.metric(scope=Scope.SUITE)
            def quality():
                metric = rue.Metric()
                yield metric
                yield metric.sum


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_seed(quality):
                quality.add_record(5)


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            @rue.test.iterate.params("value", [(1,), (1,)])
            def test_remote(value, quality):
                quality.add_record(value)
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=3)

    assert suite.result.passed == 2, _failures(suite)
    [metric_result] = suite.result.metric_results
    assert metric_result.value == 7


@pytest.mark.asyncio
async def test_test_scoped_subprocess_metric_finalizes_in_parent(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_test_metric.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            @rue.resource.metric(scope=Scope.TEST)
            def quality():
                metric = rue.Metric()
                yield metric
                yield metric.sum


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(quality):
                quality.add_record(4)
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 1, _failures(suite)
    [metric_result] = suite.result.metric_results
    assert metric_result.metadata.identity.name == "quality"
    assert metric_result.value == 4


@pytest.mark.asyncio
async def test_subprocess_sut_trace_state_is_process_local(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_sut_trace.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope
            from rue.telemetry.otel.runtime import otel_runtime


            class SharedPipeline:
                def __init__(self):
                    self.labels = []

                def run(self, label):
                    self.labels.append(label)
                    with otel_runtime.start_as_current_span(f"{label}_step"):
                        return label


            @rue.resource.sut(scope=Scope.SUITE)
            def shared_pipeline():
                return rue.SUT(SharedPipeline(), methods=["run"])


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_local(shared_pipeline):
                assert shared_pipeline.instance.run("local") == "local"
                assert shared_pipeline.instance.labels == ["local"]


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(shared_pipeline):
                assert shared_pipeline.instance.run("remote") == "remote"
                assert shared_pipeline.instance.labels == ["remote"]
                assert {span.name for span in shared_pipeline.all_spans} == {
                    "sut.shared_pipeline.run",
                    "remote_step",
                }


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after(shared_pipeline):
                assert shared_pipeline.instance.labels == ["local"]
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2, otel=True)

    assert suite.result.passed == 3, _failures(suite)
    remote_execution = next(
        execution
        for execution in suite.result.test_executions
        if execution.definition.spec.name == "test_remote"
    )
    span_names = {
        span["name"]
        for artifact in remote_execution.telemetry_artifacts
        for span in getattr(artifact, "spans", [])
    }
    assert "remote_step" in span_names


@pytest.mark.asyncio
async def test_test_scoped_subprocess_sut_finalization_error_transfers(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_test_sut_finalization.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            @rue.resource.sut(scope=Scope.TEST)
            def checked_pipeline():
                sut = rue.SUT(lambda: "ok")
                yield sut
                raise AssertionError("sut finalized in worker")


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(checked_pipeline):
                assert checked_pipeline.instance() == "ok"
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 0
    [failure] = _failures(suite)
    assert failure[0] == "test_remote"
    assert failure[1] == "error"
    assert "Subprocess resource errors" in (failure[2] or "")


@pytest.mark.asyncio
async def test_suite_scoped_subprocess_sut_finalizes_in_parent(
    tmp_path: Path,
):
    finalized_path = tmp_path / "finalized.txt"
    module_path = tmp_path / "test_remote_suite_sut_finalization.py"
    module_path.write_text(
        dedent(
            f"""
            import os
            from pathlib import Path

            import rue
            from rue import ExecutionBackend
            from rue.resources.models import Scope


            PARENT_PID = os.getpid()
            FINALIZED_PATH = Path({str(finalized_path)!r})


            @rue.resource.sut(scope=Scope.SUITE)
            def checked_suite_pipeline():
                sut = rue.SUT(lambda: "ok")
                yield sut
                FINALIZED_PATH.write_text(str(os.getpid()))


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(checked_suite_pipeline):
                assert checked_suite_pipeline.instance() == "ok"
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=2)

    assert suite.result.passed == 1, _failures(suite)
    assert finalized_path.read_text() == str(os.getpid())


@pytest.mark.asyncio
async def test_main_backend_waits_for_subprocess_without_resource_merge(
    tmp_path: Path,
):
    remote_done_path = tmp_path / "remote_done.txt"
    module_path = tmp_path / "test_backend_queue_barrier.py"
    module_path.write_text(
        dedent(
            f"""
            import asyncio
            import time
            from pathlib import Path

            import rue
            from rue import ExecutionBackend
            from rue.resources import resource
            from rue.resources.models import Scope


            REMOTE_DONE_PATH = Path({str(remote_done_path)!r})


            @resource(scope=Scope.SUITE)
            def events():
                return []


            @rue.test
            async def test_async(events):
                await asyncio.sleep(0.1)
                events.append("async")


            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote(events):
                time.sleep(0.05)
                events.append("remote")
                REMOTE_DONE_PATH.write_text("done")


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_barrier(events):
                assert REMOTE_DONE_PATH.read_text() == "done"
                assert events == ["async"]
                events.append("main")


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after(events):
                assert events == ["async", "main"]
            """
        )
    )

    suite = await _suite_module(module_path, concurrency=3)

    assert suite.result.passed == 4, _failures(suite)
