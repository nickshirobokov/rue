from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
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
            from rue.resources import resource
            from rue.resources.models import Scope

            @resource(scope=Scope.PROCESS)
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

            @rue.test
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
            concurrency=1,
        ),
        reporters=[NullReporter()],
    ).run(items=items)

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

            @resource(scope=Scope.PROCESS)
            def shared_events():
                return []

            @resource(scope=Scope.PROCESS)
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
    ).run(items=items)

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
