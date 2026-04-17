"""Tests for the remote execution backend."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock

import pytest

import rue
from rue.config import Config
from rue.resources import ResourceResolver, registry, resource
from rue.resources.models import Scope
from rue.testing.execution.factory import DefaultTestFactory
from rue.testing.execution.local.single import LocalSingleTest
from rue.testing.execution.remote.single import (
    ExecutorPayload,
    RemoteSingleTest,
)
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import (
    BackendModifier,
    IterateModifier,
    TestResult,
    TestStatus,
)
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import make_definition, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


class FakePool:
    """Stand-in for ProcessPoolExecutor that resolves a canned TestResult."""

    def __init__(self, result: TestResult) -> None:
        self._result = result
        self.submitted: list[tuple[Any, ...]] = []

    def submit(self, fn, *args, **kwargs) -> Future:
        self.submitted.append((fn, args, kwargs))
        future: Future = Future()
        future.set_result(self._result)
        return future


# ---------------------------------------------------------------------------
# backend decorator + BackendModifier
# ---------------------------------------------------------------------------


class TestBackendDecorator:
    def test_attaches_backend_modifier(self):
        @rue.test.backend("subprocess")
        def sample():
            pass

        assert sample.__rue_test__ is True
        assert sample.__rue_modifiers__ == [
            BackendModifier(backend=ExecutionBackend.SUBPROCESS)
        ]

    def test_composes_with_iterate(self):
        @rue.test.backend("subprocess")
        @rue.test.iterate(3)
        def sample():
            pass

        assert sample.__rue_modifiers__ == [
            IterateModifier(count=3, min_passes=3),
            BackendModifier(backend=ExecutionBackend.SUBPROCESS),
        ]

    def test_spec_carries_modifier_after_get_execution_from_fn(self):
        @rue.test.backend("subprocess")
        def sample():
            pass

        item = make_definition("sample")
        item.spec.get_execution_from_fn(sample)
        assert (
            BackendModifier(backend=ExecutionBackend.SUBPROCESS) in item.spec.modifiers
        )

    def test_accepts_execution_backend_enum(self):
        @rue.test.backend(ExecutionBackend.SUBPROCESS)
        def sample():
            pass

        assert sample.__rue_modifiers__ == [
            BackendModifier(backend=ExecutionBackend.SUBPROCESS)
        ]


# ---------------------------------------------------------------------------
# factory dispatch
# ---------------------------------------------------------------------------


class TestFactoryDispatch:
    def _definition(self, *modifiers):
        return make_definition("sample", modifiers=list(modifiers))

    def test_local_by_default(self):
        factory = DefaultTestFactory(config=Config())
        built = factory.build(self._definition())
        assert isinstance(built, LocalSingleTest)

    def test_remote_when_backend_modifier_present(self):
        pool = FakePool(TestResult(status=TestStatus.PASSED, duration_ms=0))
        factory = DefaultTestFactory(config=Config(), pool=pool)

        built = factory.build(
            self._definition(BackendModifier(backend=ExecutionBackend.SUBPROCESS))
        )

        assert isinstance(built, RemoteSingleTest)
        assert built.pool is pool

    def test_remote_backend_requires_pool(self):
        factory = DefaultTestFactory(config=Config())

        with pytest.raises(
            RuntimeError,
            match="subprocess backend requires a ProcessPoolExecutor",
        ):
            factory.build(
                self._definition(BackendModifier(backend=ExecutionBackend.SUBPROCESS))
            )

    def test_invalid_backend_string_rejected(self):
        with pytest.raises(ValueError):
            ExecutionBackend("nope")

    def test_backend_propagates_through_iterate(self):
        pool = FakePool(TestResult(status=TestStatus.PASSED, duration_ms=0))
        factory = DefaultTestFactory(config=Config(), pool=pool)

        built = factory.build(
            self._definition(
                BackendModifier(backend=ExecutionBackend.SUBPROCESS),
                IterateModifier(count=3, min_passes=3),
            )
        )

        assert len(built.children) == 3
        assert all(isinstance(c, RemoteSingleTest) for c in built.children)


# ---------------------------------------------------------------------------
# RemoteSingleTest payload building + ExecutedTest wiring
# ---------------------------------------------------------------------------


class TestRemoteSingleTest:
    def test_rejects_modifiers(self):
        pool = FakePool(TestResult(status=TestStatus.PASSED, duration_ms=0))
        with pytest.raises(
            ValueError, match="RemoteSingleTest should not have modifiers"
        ):
            RemoteSingleTest(
                definition=make_definition(
                    modifiers=[IterateModifier(count=2, min_passes=2)]
                ),
                params={},
                pool=pool,
            )

    @pytest.mark.asyncio
    async def test_builds_payload_and_wraps_result(self, tmp_path: Path):
        @resource(scope=Scope.MODULE)
        def shared_value():
            return 42

        def sample(shared_value):
            _ = shared_value

        definition = make_definition(
            "sample",
            fn=sample,
            params=["shared_value"],
            suite_root=tmp_path,
        )

        expected = TestResult(status=TestStatus.PASSED, duration_ms=12.3)
        pool = FakePool(expected)
        remote = RemoteSingleTest(
            definition=definition,
            params={},
            pool=pool,
        )

        execution = await remote.execute(ResourceResolver(registry))

        assert execution.definition is definition
        assert execution.result is expected
        assert execution.status == TestStatus.PASSED

        assert len(pool.submitted) == 1
        submitted_fn, args, _ = pool.submitted[0]
        from rue.testing.execution.remote.worker import run_remote_test
        assert submitted_fn is run_remote_test
        (payload,) = args
        assert isinstance(payload, ExecutorPayload)
        assert payload.spec is definition.spec
        assert payload.suite_root == tmp_path
        assert payload.setup_chain == ()
        assert [
            s.name for s in payload.blueprint.resolution_order
        ] == ["shared_value"]

    @pytest.mark.asyncio
    async def test_skips_when_stopped(self):
        pool = FakePool(TestResult(status=TestStatus.PASSED, duration_ms=0))
        remote = RemoteSingleTest(
            definition=make_definition("sample"),
            params={},
            pool=pool,
            is_stopped=lambda: True,
        )

        execution = await remote.execute(ResourceResolver(registry))

        assert execution.status == TestStatus.SKIPPED
        assert pool.submitted == []

    @pytest.mark.asyncio
    async def test_honors_skip_reason(self):
        pool = FakePool(TestResult(status=TestStatus.PASSED, duration_ms=0))
        definition = make_definition("sample", skip_reason="no thanks")

        remote = RemoteSingleTest(
            definition=definition,
            params={},
            pool=pool,
        )

        execution = await remote.execute(ResourceResolver(registry))

        assert execution.status == TestStatus.SKIPPED
        assert "no thanks" in str(execution.result.error)
        assert pool.submitted == []

    @pytest.mark.asyncio
    async def test_calls_on_complete(self):
        pool = FakePool(TestResult(status=TestStatus.PASSED, duration_ms=0))
        on_complete = MagicMock()

        async def capture(execution):
            on_complete(execution)

        remote = RemoteSingleTest(
            definition=make_definition("sample"),
            params={},
            pool=pool,
            on_complete=capture,
        )

        execution = await remote.execute(ResourceResolver(registry))

        on_complete.assert_called_once_with(execution)


# ---------------------------------------------------------------------------
# End-to-end: real ProcessPoolExecutor via Runner
# ---------------------------------------------------------------------------


class TestRemoteEndToEnd:
    @pytest.mark.asyncio
    async def test_runs_remote_test_in_worker(
        self,
        tmp_path: Path,
        null_reporter: NullReporter,
    ):
        """A test tagged with backend("subprocess") runs in a real worker process.

        The test writes its PID to a shared file; after the run, the parent
        checks that the PID differs from its own — proving execution happened
        out-of-process.
        """
        pid_file = tmp_path / "worker.pid"
        module_path = tmp_path / "test_remote_sample.py"
        module_path.write_text(
            dedent(
                f"""
                import os
                import rue

                @rue.test.backend("subprocess")
                def test_runs_remote():
                    with open({str(pid_file)!r}, "w") as f:
                        f.write(str(os.getpid()))
                    assert 1 + 1 == 2
                """
            )
        )

        items = materialize_tests(module_path)
        runner = Runner(reporters=[null_reporter])
        run = await runner.run(items=items)

        assert run.result.passed == 1
        assert run.result.failed == 0
        assert run.result.errors == 0

        recorded_pid = int(pid_file.read_text())
        import os as _os  # local import so the worker's os import is used above
        assert recorded_pid != _os.getpid(), (
            "remote test should not run in the parent process"
        )

    @pytest.mark.asyncio
    async def test_remote_test_with_mixed_resource_strategies(
        self,
        tmp_path: Path,
        null_reporter: NullReporter,
    ):
        """Remote run exercises all three resource transfer cases at once:

        * ``plain_value`` — serializable, injected directly into the test →
          SERIALIZE strategy, shipped in the blueprint.
        * ``shared_lock`` — non-serializable (``threading.Lock``), injected
          directly into the test → RE_RESOLVE strategy, re-resolved on the
          worker via the registry populated by the setup chain.
        * ``derived_value`` — serializable, depends on ``plain_value`` →
          SERIALIZE strategy, dependency graph crosses the boundary.
        """
        module_path = tmp_path / "test_remote_resources.py"
        module_path.write_text(
            dedent(
                """
                import threading
                import rue
                from rue.resources import resource
                from rue.resources.models import Scope

                @resource(scope=Scope.MODULE)
                def plain_value():
                    return {"key": "hello"}

                @resource(scope=Scope.MODULE)
                def shared_lock():
                    return threading.Lock()

                @resource(scope=Scope.MODULE)
                def derived_value(plain_value):
                    return plain_value["key"] + "-derived"

                @rue.test.backend("subprocess")
                def test_three_resources(plain_value, shared_lock, derived_value):
                    assert plain_value == {"key": "hello"}
                    assert hasattr(shared_lock, "acquire")
                    assert hasattr(shared_lock, "release")
                    assert derived_value == "hello-derived"
                """
            )
        )

        items = materialize_tests(module_path)
        runner = Runner(reporters=[null_reporter])
        run = await runner.run(items=items)

        assert run.result.passed == 1, run.result.executions[0].result.error
        assert run.result.failed == 0
        assert run.result.errors == 0
