from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
from rue.resources import ResourceResolver, registry
from rue.testing.models import TestStatus
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import materialize_tests


@pytest.mark.asyncio
async def test_iterated_subprocess_children_keep_distinct_process_updates(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_iterate_conflict.py"
    module_path.write_text(
        dedent(
            """
            import time
            import rue
            from rue import ExecutionBackend
            from rue.resources import resource
            from rue.resources.models import Scope

            @resource(scope=Scope.RUN)
            def shared_events():
                return []

            @rue.test.backend("subprocess")
            @rue.test.iterate.params("event", [("one",), ("two",)])
            def test_remote(event, shared_events):
                if event == "one":
                    time.sleep(0.1)
                else:
                    time.sleep(0.3)
                shared_events.append(event)

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after(shared_events):
                assert shared_events == ["one", "two"]
            """
        )
    )

    items = materialize_tests(module_path)
    run = await Runner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=4,
        ),
        reporters=[NullReporter()],
    ).run(items=items, resolver=ResourceResolver(registry))

    after_execution = next(
        execution
        for execution in run.result.executions
        if execution.definition.spec.name == "test_after"
    )

    assert after_execution.status == TestStatus.PASSED, [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_local_and_subprocess_updates_preserve_process_identity(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_local_identity.py"
    module_path.write_text(
        dedent(
            """
            import time
            import rue
            from rue.resources import resource
            from rue.resources.models import Scope

            @resource(scope=Scope.RUN)
            def shared_events():
                return []

            @resource(scope=Scope.RUN)
            def shared_meta():
                return {}

            @rue.test
            def test_local(shared_events, shared_meta):
                shared_meta.setdefault("object_id", id(shared_events))
                time.sleep(0.1)
                shared_events.append("local")

            @rue.test.backend("subprocess")
            def test_remote(shared_events):
                time.sleep(0.3)
                shared_events.append("remote")

            @rue.test
            def test_after(shared_events, shared_meta):
                deadline = time.time() + 10
                while len(shared_events) < 2 and time.time() < deadline:
                    time.sleep(0.05)
                assert shared_events == ["local", "remote"]
                assert shared_meta["object_id"] == id(shared_events)
            """
        )
    )

    items = materialize_tests(module_path)
    run = await Runner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=2,
        ),
        reporters=[NullReporter()],
    ).run(items=items, resolver=ResourceResolver(registry))

    after_execution = next(
        execution
        for execution in run.result.executions
        if execution.definition.spec.name == "test_after"
    )

    assert after_execution.status == TestStatus.PASSED, [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_local_and_subprocess_nested_updates_merge_without_replacing_root(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_local_nested_merge.py"
    module_path.write_text(
        dedent(
            """
            import time
            import rue
            from rue.resources import resource
            from rue.resources.models import Scope

            class Branch:
                def __init__(self):
                    self.left = []
                    self.right = []

            class SharedState:
                def __init__(self):
                    self.branch = Branch()
                    self.meta = {}

            @resource(scope=Scope.RUN)
            def shared_state():
                return SharedState()

            @rue.test
            def test_local(shared_state):
                shared_state.meta["root_id"] = id(shared_state)
                shared_state.meta["branch_id"] = id(shared_state.branch)
                time.sleep(0.1)
                shared_state.branch.left.append("local")

            @rue.test.backend("subprocess")
            def test_remote(shared_state):
                time.sleep(0.3)
                replacement = Branch()
                replacement.right.append("remote")
                shared_state.branch = replacement

            @rue.test
            def test_after(shared_state):
                deadline = time.time() + 10
                while len(shared_state.branch.right) < 1 and time.time() < deadline:
                    time.sleep(0.05)
                assert shared_state.meta["root_id"] == id(shared_state)
                assert shared_state.meta["branch_id"] == id(shared_state.branch)
                assert shared_state.branch.left == ["local"]
                assert shared_state.branch.right == ["remote"]
            """
        )
    )

    items = materialize_tests(module_path)
    run = await Runner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=2,
        ),
        reporters=[NullReporter()],
    ).run(items=items, resolver=ResourceResolver(registry))

    after_execution = next(
        execution
        for execution in run.result.executions
        if execution.definition.spec.name == "test_after"
    )

    assert after_execution.status == TestStatus.PASSED, [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_local_and_subprocess_shared_sut_trace_state_stays_isolated(
    tmp_path: Path,
):
    module_path = tmp_path / "test_remote_local_shared_sut_trace.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time
            import rue
            from rue.resources.models import Scope
            from rue.telemetry.otel.runtime import otel_runtime

            class SharedPipeline:
                def run(self, label):
                    with otel_runtime.start_as_current_span(f"{label}_step"):
                        return label

            @rue.resource.sut(scope=Scope.RUN)
            def shared_pipeline():
                return rue.SUT(SharedPipeline(), methods=["run"])

            @rue.test
            async def test_local(shared_pipeline):
                await asyncio.sleep(0.05)
                assert shared_pipeline.instance.run("local") == "local"
                assert {span.name for span in shared_pipeline.all_spans} == {
                    "sut.shared_pipeline.run",
                    "local_step",
                }

            @rue.test.backend("subprocess")
            def test_remote(shared_pipeline):
                time.sleep(0.15)
                assert shared_pipeline.instance.run("remote") == "remote"
                assert {span.name for span in shared_pipeline.all_spans} == {
                    "sut.shared_pipeline.run",
                    "remote_step",
                }
            """
        )
    )

    items = materialize_tests(module_path)
    run = await Runner(
        config=Config.model_construct(
            otel=True,
            db_enabled=False,
            concurrency=2,
        ),
        reporters=[NullReporter()],
    ).run(items=items, resolver=ResourceResolver(registry))

    assert run.result.passed == 2, [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_main_backend_waits_for_local_and_subprocess_stage(
    tmp_path: Path,
):
    module_path = tmp_path / "test_backend_queue_barrier.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time
            import rue
            from rue import ExecutionBackend
            from rue.resources import resource
            from rue.resources.models import Scope

            @resource(scope=Scope.RUN)
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

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_barrier(events):
                assert len(events) == 2
                assert set(events) == {"async", "remote"}
                events.append("main")

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after(events):
                assert events[-1] == "main"
                assert set(events[:-1]) == {"async", "remote"}
            """
        )
    )

    items = materialize_tests(module_path)
    run = await Runner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=3,
        ),
        reporters=[NullReporter()],
    ).run(items=items, resolver=ResourceResolver(registry))

    assert run.result.passed == 4, [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]
