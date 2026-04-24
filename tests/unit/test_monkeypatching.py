"""Tests for Rue runtime monkeypatching."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
from rue.resources import registry
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def make_runner() -> Runner:
    return Runner(
        config=Config.model_construct(db_enabled=False, concurrency=4),
        reporters=[NullReporter()],
    )


class ImmediatePool:
    """Process-pool test double that runs the worker entrypoint immediately."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1)

    def submit(self, fn, *args, **kwargs) -> Future:
        return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_test_scoped_patches_are_isolated_between_concurrent_cases(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_cases.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import rue
            from rue import ExecutionBackend

            class Service:
                def call(self):
                    return "original"

            @rue.test.iterate.params(
                "value,pause",
                [("left", 0.05), ("right", 0.01)],
            )
            async def test_patch(value, pause, monkeypatch):
                monkeypatch.setattr(Service, "call", lambda self: value)
                await asyncio.sleep(pause)
                assert Service().call() == value

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert Service().call() == "original"
            """
        )
    )

    run = await make_runner().run(items=materialize_tests(module_path))

    assert run.result.passed == 2, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_resource_scoped_patch_follows_dependent_tests(
    tmp_path: Path,
):
    module_path = tmp_path / "test_resource_patch.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend

            class API:
                mode = "original"

            api = API()
            calls = 0

            @rue.resource
            def patched_api(monkeypatch):
                global calls
                calls += 1
                if calls == 1:
                    monkeypatch.setattr(api, "mode", "patched")
                return api

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_first_use(patched_api):
                assert api.mode == "patched"
                assert patched_api.mode == "patched"

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_second_use(patched_api):
                assert api.mode == "original"
                assert patched_api.mode == "original"

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert api.mode == "original"
            """
        )
    )

    run = await make_runner().run(items=materialize_tests(module_path))

    assert run.result.passed == 3, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_autouse_patch_applies_in_subprocess_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    pool = ImmediatePool()
    monkeypatch.setattr(
        "rue.testing.execution.single.get_process_pool",
        lambda: pool,
    )
    module_path = tmp_path / "test_remote_autouse_patch.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend

            def call():
                return "original"

            @rue.resource(scope="process", autouse=True)
            def patch_call(monkeypatch):
                monkeypatch.setattr_path(__name__ + ":call", lambda: "patched")

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote():
                assert call() == "patched"
            """
        )
    )

    try:
        run = await make_runner().run(items=materialize_tests(module_path))
    finally:
        pool.shutdown()

    assert run.result.passed == 1, [
        execution.result.error for execution in run.result.executions
    ]
