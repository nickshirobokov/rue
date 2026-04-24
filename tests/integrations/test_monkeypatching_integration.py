from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
from rue.resources import registry
from rue.testing.models import TestStatus
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def _failed_executions(run):
    rows = []
    pending = list(run.result.executions)
    while pending:
        execution = pending.pop()
        if execution.status is not TestStatus.PASSED:
            rows.append(
                (
                    execution.node_key,
                    execution.status.value,
                    str(execution.result.error)
                    if execution.result.error
                    else None,
                )
            )
        pending.extend(execution.sub_executions)
    return rows


async def _run_module(module_path: Path):
    return await Runner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=6,
        ),
        reporters=[NullReporter()],
    ).run(items=materialize_tests(module_path))


@pytest.mark.asyncio
async def test_iterated_patches_to_same_object_are_execution_isolated(
    tmp_path: Path,
):
    module_path = tmp_path / "test_iterated_monkeypatch_isolation.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend


            class Target:
                def value(self):
                    return "original"


            target = Target()


            def patch_target(monkeypatch, value):
                monkeypatch.setattr(
                    Target,
                    "value",
                    lambda self, value=value: value,
                )


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.12), ("right", 0.04), ("center", 0.08)],
            )
            def test_sync(case, pause, monkeypatch):
                expected = f"sync:{case}"
                assert target.value() == "original"
                patch_target(monkeypatch, expected)
                time.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.03), ("right", 0.09), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.MAIN)
            async def test_async_main(case, pause, monkeypatch):
                expected = f"main:{case}"
                assert target.value() == "original"
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.10), ("right", 0.02), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            async def test_async_subprocess(case, pause, monkeypatch):
                expected = f"subprocess:{case}"
                assert target.value() == "original"
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target.value() == "original"
            """
        )
    )

    run = await _run_module(module_path)

    assert run.result.passed == 4, _failed_executions(run)


@pytest.mark.asyncio
async def test_resource_and_test_patches_to_same_object_are_isolated(
    tmp_path: Path,
):
    module_path = tmp_path / "test_resource_monkeypatch_isolation.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend


            class Target:
                def value(self):
                    return "original"


            target = Target()


            def patch_target(monkeypatch, value):
                monkeypatch.setattr(
                    Target,
                    "value",
                    lambda self, value=value: value,
                )


            @rue.resource(scope="process")
            def sync_patch(monkeypatch):
                patch_target(monkeypatch, "resource:sync")
                return "resource:sync"


            @rue.resource(scope="process")
            def main_patch(monkeypatch):
                patch_target(monkeypatch, "resource:main")
                return "resource:main"


            @rue.resource(scope="process")
            def subprocess_patch(monkeypatch):
                patch_target(monkeypatch, "resource:subprocess")
                return "resource:subprocess"


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.12), ("right", 0.04), ("center", 0.08)],
            )
            def test_sync(case, pause, sync_patch, monkeypatch):
                expected = f"test:sync:{case}"
                assert target.value() == sync_patch
                patch_target(monkeypatch, expected)
                time.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.03), ("right", 0.09), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.MAIN)
            async def test_async_main(case, pause, main_patch, monkeypatch):
                expected = f"test:main:{case}"
                assert target.value() == main_patch
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.iterate.params(
                "case,pause",
                [("left", 0.10), ("right", 0.02), ("center", 0.06)],
            )
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            async def test_async_subprocess(
                case,
                pause,
                subprocess_patch,
                monkeypatch,
            ):
                expected = f"test:subprocess:{case}"
                assert target.value() == subprocess_patch
                patch_target(monkeypatch, expected)
                await asyncio.sleep(pause)
                assert target.value() == expected


            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after_without_resources():
                assert target.value() == "original"
            """
        )
    )

    run = await _run_module(module_path)

    assert run.result.passed == 4, _failed_executions(run)
