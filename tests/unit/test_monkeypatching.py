"""Tests for Rue runtime monkeypatching."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from textwrap import dedent
from uuid import uuid4

import pytest

from rue.context.scopes import Scope, ScopeOwner
from rue.patching import MonkeyPatch
from rue.patching.runtime import (
    PatchContext,
    PatchLifetime,
    PatchStore,
)
from rue.resources import ResourceResolver, registry
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import make_run_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


def make_runner() -> Runner:
    make_run_context(db_enabled=False, concurrency=4)
    return Runner(
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


def test_monkeypatch_stores_lifetime_not_resolver() -> None:
    owner = ScopeOwner(scope=Scope.TEST, execution_id=uuid4())
    lifetime = PatchLifetime(owner=owner, store=PatchStore())
    monkeypatch = MonkeyPatch(lifetime=lifetime)

    assert monkeypatch.lifetime is lifetime
    assert monkeypatch.scope is Scope.TEST
    assert not hasattr(monkeypatch, "resolver")


def test_patch_owner_is_active_from_explicit_patch_context(
    tmp_path: Path,
) -> None:
    execution_id = uuid4()
    run_id = uuid4()
    module_path = tmp_path / "test_module.py"
    context = PatchContext(
        execution_id=execution_id,
        module_path=module_path.resolve(),
        run_id=run_id,
    )

    assert ScopeOwner(
        scope=Scope.TEST,
        execution_id=execution_id,
        run_id=run_id,
    ).is_active(
        execution_id=context.execution_id,
        run_id=context.run_id,
        module_path=context.module_path,
    )
    assert ScopeOwner(
        scope=Scope.MODULE,
        run_id=run_id,
        module_path=module_path.resolve(),
    ).is_active(
        execution_id=context.execution_id,
        run_id=context.run_id,
        module_path=context.module_path,
    )
    assert ScopeOwner(scope=Scope.RUN, run_id=run_id).is_active(
        execution_id=context.execution_id,
        run_id=context.run_id,
        module_path=context.module_path,
    )
    assert not ScopeOwner(
        scope=Scope.TEST,
        execution_id=uuid4(),
        run_id=run_id,
    ).is_active(
        execution_id=context.execution_id,
        run_id=context.run_id,
        module_path=context.module_path,
    )
    assert not ScopeOwner(
        scope=Scope.MODULE,
        run_id=run_id,
        module_path=(tmp_path / "other.py").resolve(),
    ).is_active(
        execution_id=context.execution_id,
        run_id=context.run_id,
        module_path=context.module_path,
    )
    assert not ScopeOwner(scope=Scope.RUN, run_id=uuid4()).is_active(
        execution_id=context.execution_id,
        run_id=context.run_id,
        module_path=context.module_path,
    )
    assert not ScopeOwner(
        scope=Scope.TEST,
        execution_id=execution_id,
        run_id=run_id,
    ).is_active(execution_id=None, run_id=None, module_path=None)


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

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 2, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_resource_monkeypatch_creates_test_scoped_patch(
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

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 3, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_delattr_hides_attribute_in_active_test_scope(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_delattr.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import rue
            from rue import ExecutionBackend

            class Target:
                value = "original"

            @rue.test.iterate.params(
                "pause",
                [0.05, 0.01],
            )
            async def test_delete(pause, monkeypatch):
                assert Target.value == "original"
                monkeypatch.delattr(Target, "value")
                await asyncio.sleep(pause)
                assert not hasattr(Target, "value")

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_missing_delete_is_optional(monkeypatch):
                monkeypatch.delattr(Target, "missing", raising=False)

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert Target.value == "original"
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 3, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_setitem_patches_are_isolated_between_concurrent_cases(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_setitem.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import rue
            from rue import ExecutionBackend

            target = {"value": "original"}

            @rue.test.iterate.params(
                "value,pause",
                [("left", 0.05), ("right", 0.01)],
            )
            async def test_patch_item(value, pause, monkeypatch):
                assert target["value"] == "original"
                monkeypatch.setitem(target, "value", value)
                await asyncio.sleep(pause)
                assert target["value"] == value

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target["value"] == "original"
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 2, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_setitem_replaces_list_items_between_concurrent_cases(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_list_replace.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import rue
            from rue import ExecutionBackend

            target = ["original"]

            @rue.test.iterate.params(
                "value,pause",
                [("left", 0.05), ("right", 0.01)],
            )
            async def test_patch_list_item(value, pause, monkeypatch):
                assert target[0] == "original"
                monkeypatch.setitem(
                    target,
                    value,
                    idx=0,
                    replace=True,
                )
                await asyncio.sleep(pause)
                assert target[0] == value

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target == ["original"]
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 2, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_setitem_inserts_list_items_and_restores_on_teardown(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_list_insert.py"
    module_path.write_text(
        dedent(
            """
            import rue
            from rue import ExecutionBackend

            target = ["tail"]

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_insert_list_item(monkeypatch):
                monkeypatch.setitem(
                    target,
                    "head",
                    idx=0,
                    replace=False,
                )
                assert target == ["head", "tail"]

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target == ["tail"]
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 2, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_delitem_hides_item_in_active_test_scope(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_delitem.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import pytest
            import rue
            from rue import ExecutionBackend

            target = {"value": "original"}

            @rue.test.iterate.params(
                "pause",
                [0.05, 0.01],
            )
            async def test_delete_item(pause, monkeypatch):
                assert target["value"] == "original"
                monkeypatch.delitem(target, "value")
                await asyncio.sleep(pause)
                with pytest.raises(KeyError):
                    str(target["value"])

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_missing_delete_is_optional(monkeypatch):
                monkeypatch.delitem(target, "missing", raising=False)

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target["value"] == "original"
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 3, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_delitem_hides_list_item_in_active_test_scope(
    tmp_path: Path,
):
    module_path = tmp_path / "test_monkeypatch_list_delitem.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import pytest
            import rue
            from rue import ExecutionBackend

            target = ["original"]

            @rue.test.iterate.params(
                "pause",
                [0.05, 0.01],
            )
            async def test_delete_list_item(pause, monkeypatch):
                assert target[0] == "original"
                monkeypatch.delitem(target, idx=0, replace=True)
                await asyncio.sleep(pause)
                with pytest.raises(IndexError):
                    str(target[0])

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_missing_delete_is_optional(monkeypatch):
                monkeypatch.delitem(
                    target,
                    idx=12,
                    replace=True,
                    raising=False,
                )

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert target == ["original"]
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

    assert run.result.passed == 3, [
        execution.result.error for execution in run.result.executions
    ]


@pytest.mark.asyncio
async def test_resource_monkeypatch_creates_test_scoped_item_patches(
    tmp_path: Path,
):
    module_path = tmp_path / "test_resource_item_patch.py"
    module_path.write_text(
        dedent(
            """
            import pytest
            import rue
            from rue import ExecutionBackend

            state = {"mode": "original", "token": "secret"}
            calls = 0

            @rue.resource
            def patched_state(monkeypatch):
                global calls
                calls += 1
                if calls == 1:
                    monkeypatch.setitem(state, "mode", "patched")
                    monkeypatch.delitem(state, "token")
                return state

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_first_use(patched_state):
                assert state["mode"] == "patched"
                assert patched_state["mode"] == "patched"
                with pytest.raises(KeyError):
                    str(state["token"])

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_second_use(patched_state):
                assert state["mode"] == "original"
                assert patched_state["mode"] == "original"
                assert state["token"] == "secret"

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_after():
                assert state["mode"] == "original"
                assert state["token"] == "secret"
            """
        )
    )

    run = await make_runner().run(
        items=materialize_tests(module_path),
        resolver=ResourceResolver(registry),
    )

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

            @rue.resource(scope="run", autouse=True)
            def patch_call(monkeypatch):
                monkeypatch.setattr(__name__ + ":call", lambda: "patched")

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_remote():
                assert call() == "patched"
            """
        )
    )

    try:
        run = await make_runner().run(
            items=materialize_tests(module_path),
            resolver=ResourceResolver(registry),
        )
    finally:
        pool.shutdown()

    assert run.result.passed == 1, [
        execution.result.error for execution in run.result.executions
    ]
