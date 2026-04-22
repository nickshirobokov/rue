"""Tests for the remote execution backend."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

import rue
from rue.config import Config
from rue.resources import ResourceResolver, registry, resource
from rue.resources.models import Scope
from rue.telemetry import OtelTraceArtifact
from rue.testing.execution.factory import DefaultTestFactory
from rue.context.process_pool import CURRENT_PROCESS_POOL
from rue.testing.execution.remote.models import (
    ExecutorPayload,
    RemoteExecutionResult,
)
from rue.testing.execution.single import SingleTest
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import (
    BackendModifier,
    IterateModifier,
    TestResult,
    TestStatus,
)
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter, TraceCollectorReporter
from tests.unit.factories import make_definition, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


class FakePool:
    """Stand-in for ProcessPoolExecutor that resolves a canned TestResult.

    Doubles as the LazyProcessPool holder — ``get()`` returns ``self`` so the
    same instance can be bound to ``CURRENT_PROCESS_POOL``.
    """

    def __init__(self, result: RemoteExecutionResult) -> None:
        self._result = result
        self.submitted: list[tuple[Any, ...]] = []

    def submit(self, fn, *args, **kwargs) -> Future:
        self.submitted.append((fn, args, kwargs))
        future: Future = Future()
        future.set_result(self._result)
        return future

    def get(self) -> "FakePool":
        return self


class BlockingPool(FakePool):
    def __init__(self, result: RemoteExecutionResult, *, delay: float) -> None:
        super().__init__(result)
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def submit(self, fn, *args, **kwargs) -> Future:
        self.submitted.append((fn, args, kwargs))
        future: Future = Future()

        def complete() -> None:
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(self.delay)
            with self._lock:
                self.active -= 1
            future.set_result(self._result)

        threading.Thread(target=complete, daemon=True).start()
        return future


def make_runner(reporter) -> Runner:
    return Runner(
        config=Config.model_construct(db_enabled=False),
        reporters=[reporter],
    )


@contextmanager
def bind_pool(pool: FakePool):
    token = CURRENT_PROCESS_POOL.set(pool)  # type: ignore[arg-type]
    try:
        yield pool
    finally:
        CURRENT_PROCESS_POOL.reset(token)


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
        assert item.spec.modifiers == (
            BackendModifier(backend=ExecutionBackend.SUBPROCESS),
        )

    def test_accepts_execution_backend_enum(self):
        @rue.test.backend(ExecutionBackend.SUBPROCESS)
        def sample():
            pass

        assert sample.__rue_modifiers__ == [
            BackendModifier(backend=ExecutionBackend.SUBPROCESS)
        ]

    def test_removed_local_backend_raises_value_error(self):
        with pytest.raises(ValueError, match="local"):
            @rue.test.backend("local")
            def sample():
                pass

    def test_rejects_multiple_backend_decorators(self):
        @rue.test.backend("main")
        @rue.test.backend("subprocess")
        def sample():
            pass

        item = make_definition("sample")
        item.spec.get_execution_from_fn(sample)

        assert (
            item.spec.definition_error
            == "Multiple @rue.test.backend(...) decorators are not supported."
        )


# ---------------------------------------------------------------------------
# factory dispatch
# ---------------------------------------------------------------------------


class TestFactoryDispatch:
    def _definition(self, *, backend=ExecutionBackend.ASYNCIO, modifiers=()):
        return make_definition(
            "sample",
            backend=backend,
            modifiers=list(modifiers),
        )

    def test_local_by_default(self):
        factory = DefaultTestFactory(config=Config(), run_id=uuid4())
        built = factory.build(self._definition())
        assert isinstance(built, SingleTest)
        assert built.backend is ExecutionBackend.ASYNCIO

    def test_remote_when_backend_modifier_present(self):
        factory = DefaultTestFactory(config=Config(), run_id=uuid4())

        built = factory.build(
            self._definition(backend=ExecutionBackend.SUBPROCESS)
        )

        assert isinstance(built, SingleTest)

    def test_invalid_backend_string_rejected(self):
        with pytest.raises(ValueError):
            ExecutionBackend("nope")

    def test_backend_propagates_through_iterate(self):
        factory = DefaultTestFactory(config=Config(), run_id=uuid4())

        built = factory.build(
            self._definition(
                backend=ExecutionBackend.SUBPROCESS,
                modifiers=(IterateModifier(count=3, min_passes=3),),
            )
        )

        assert len(built.children) == 3
        assert all(isinstance(c, SingleTest) for c in built.children)


# ---------------------------------------------------------------------------
# SingleTest subprocess payload building + ExecutedTest wiring
# ---------------------------------------------------------------------------


class TestSingleTestSubprocess:
    def test_rejects_modifiers(self):
        with pytest.raises(ValueError, match="SingleTest should not have modifiers"):
            SingleTest(
                definition=make_definition(
                    modifiers=[IterateModifier(count=2, min_passes=2)],
                    backend=ExecutionBackend.SUBPROCESS,
                ),
                params={},
                backend=ExecutionBackend.SUBPROCESS,
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

        expected = RemoteExecutionResult(
            result=TestResult(status=TestStatus.PASSED, duration_ms=12.3),
            telemetry_artifacts=(),
            sync_update=b"",
        )
        remote = SingleTest(
            definition=definition,
            params={},
            backend=ExecutionBackend.SUBPROCESS,
            config=Config.model_construct(otel=False),
            run_id=UUID(int=1),
        )

        with bind_pool(FakePool(expected)) as pool:
            execution = await remote.execute(ResourceResolver(registry))

        assert execution.definition is definition
        assert execution.result is expected.result
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
        assert payload.config.otel is False
        assert payload.run_id == UUID(int=1)
        assert payload.execution_id == execution.execution_id
        assert [s.name for s in payload.snapshot.resolution_order] == [
            "shared_value"
        ]

    @pytest.mark.asyncio
    async def test_preserves_worker_telemetry_artifacts(self, tmp_path: Path):
        definition = make_definition(
            "sample",
            fn=lambda: None,
            suite_root=tmp_path,
        )

        class ArtifactPool(FakePool):
            def submit(self, fn, *args, **kwargs) -> Future:
                self.submitted.append((fn, args, kwargs))
                future: Future = Future()
                (payload,) = args
                future.set_result(
                    RemoteExecutionResult(
                        result=TestResult(
                            status=TestStatus.PASSED, duration_ms=12.3
                        ),
                        telemetry_artifacts=(
                            OtelTraceArtifact(
                                run_id=payload.run_id,
                                execution_id=payload.execution_id,
                                trace_id="abc",
                                spans=[],
                            ),
                        ),
                        sync_update=b"",
                    )
                )
                return future

        remote = SingleTest(
            definition=definition,
            params={},
            backend=ExecutionBackend.SUBPROCESS,
            config=Config.model_construct(otel=True),
            run_id=UUID(int=1),
        )

        with bind_pool(ArtifactPool(RemoteExecutionResult(
            result=TestResult(status=TestStatus.PASSED, duration_ms=0),
            telemetry_artifacts=(),
            sync_update=b"",
        ))) as pool:
            execution = await remote.execute(ResourceResolver(registry))

        assert len(pool.submitted) == 1
        assert len(execution.telemetry_artifacts) == 1
        artifact = execution.telemetry_artifacts[0]
        assert isinstance(artifact, OtelTraceArtifact)
        assert artifact.run_id == UUID(int=1)
        assert artifact.execution_id == execution.execution_id

    @pytest.mark.asyncio
    async def test_skips_when_stopped(self):
        remote = SingleTest(
            definition=make_definition("sample"),
            params={},
            backend=ExecutionBackend.SUBPROCESS,
            is_stopped=lambda: True,
        )

        with bind_pool(
            FakePool(
                RemoteExecutionResult(
                    result=TestResult(status=TestStatus.PASSED, duration_ms=0),
                    telemetry_artifacts=(),
                    sync_update=b"",
                )
            )
        ) as pool:
            execution = await remote.execute(ResourceResolver(registry))

        assert execution.status == TestStatus.SKIPPED
        assert pool.submitted == []

    @pytest.mark.asyncio
    async def test_honors_skip_reason(self):
        definition = make_definition(
            "sample",
            skip_reason="no thanks",
        )

        remote = SingleTest(
            definition=definition,
            params={},
            backend=ExecutionBackend.SUBPROCESS,
        )

        with bind_pool(
            FakePool(
                RemoteExecutionResult(
                    result=TestResult(status=TestStatus.PASSED, duration_ms=0),
                    telemetry_artifacts=(),
                    sync_update=b"",
                )
            )
        ) as pool:
            execution = await remote.execute(ResourceResolver(registry))

        assert execution.status == TestStatus.SKIPPED
        assert "no thanks" in str(execution.result.error)
        assert pool.submitted == []

    @pytest.mark.asyncio
    async def test_calls_on_complete(self):
        on_complete = MagicMock()

        async def capture(execution):
            on_complete(execution)

        remote = SingleTest(
            definition=make_definition("sample"),
            params={},
            backend=ExecutionBackend.SUBPROCESS,
            on_complete=capture,
        )

        with bind_pool(
            FakePool(
                RemoteExecutionResult(
                    result=TestResult(status=TestStatus.PASSED, duration_ms=0),
                    telemetry_artifacts=(),
                    sync_update=b"",
                )
            )
        ):
            execution = await remote.execute(ResourceResolver(registry))

        on_complete.assert_called_once_with(execution)

    @pytest.mark.asyncio
    async def test_respects_shared_semaphore(self, tmp_path: Path):
        expected = RemoteExecutionResult(
            result=TestResult(status=TestStatus.PASSED, duration_ms=12.3),
            telemetry_artifacts=(),
            sync_update=b"",
        )
        semaphore = asyncio.Semaphore(1)
        tests = [
            SingleTest(
                definition=make_definition(
                    f"sample_{idx}",
                    suite_root=tmp_path,
                ),
                params={},
                backend=ExecutionBackend.SUBPROCESS,
                semaphore=semaphore,
            )
            for idx in range(2)
        ]

        pool = BlockingPool(expected, delay=0.05)
        with bind_pool(pool):
            await asyncio.gather(
                *[test.execute(ResourceResolver(registry)) for test in tests]
            )

        assert pool.max_active == 1


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
        runner = make_runner(null_reporter)
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
    async def test_remote_worker_returns_trace_artifacts(
        self,
        tmp_path: Path,
        trace_reporter: TraceCollectorReporter,
    ):
        module_path = tmp_path / "test_remote_trace.py"
        module_path.write_text(
            dedent(
                """
                import rue
                from rue.predicates import predicate
                from rue.telemetry.otel.runtime import otel_runtime

                @predicate
                def is_ok(actual: str, reference: str) -> bool:
                    return actual == reference

                @rue.resource.sut(scope="process")
                def remote_pipeline():
                    def run() -> str:
                        with otel_runtime.start_as_current_span("worker_step"):
                            pass
                        with otel_runtime.start_as_current_span("openai.responses.create"):
                            pass
                        assert is_ok("ok", "ok")
                        return "ok"

                    return rue.SUT(run)

                @rue.test.backend("subprocess")
                def test_remote(remote_pipeline):
                    assert remote_pipeline.instance() == "ok"
                    assert {span.name for span in remote_pipeline.all_spans} == {
                        "sut.remote_pipeline.__call__",
                        "worker_step",
                        "openai.responses.create",
                        "predicate.is_ok",
                    }
                """
            )
        )

        items = materialize_tests(module_path)
        run = await make_runner(trace_reporter).run(items=items)

        execution = run.result.executions[0]
        assert run.result.passed == 1
        assert len(execution.telemetry_artifacts) == 1
        artifact = execution.telemetry_artifacts[0]
        assert isinstance(artifact, OtelTraceArtifact)
        assert artifact.execution_id == execution.execution_id
        assert {span["name"] for span in artifact.spans} == {
            f"test.{execution.definition.spec.full_name}",
            "sut.remote_pipeline.__call__",
            "worker_step",
            "openai.responses.create",
            "predicate.is_ok",
        }
        assert trace_reporter.artifacts == [artifact]

    @pytest.mark.asyncio
    async def test_remote_test_with_mixed_resource_states(
        self,
        tmp_path: Path,
        null_reporter: NullReporter,
    ):
        """Remote run snapshots plain data, runtime fields, and dependencies."""
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
        runner = make_runner(null_reporter)
        run = await runner.run(items=items)

        assert run.result.passed == 1, run.result.executions[0].result.error
        assert run.result.failed == 0
        assert run.result.errors == 0

    @pytest.mark.asyncio
    async def test_remote_state_is_merged_back_to_parent(
        self,
        tmp_path: Path,
        null_reporter: NullReporter,
    ):
        module_path = tmp_path / "test_remote_mergeback.py"
        module_path.write_text(
            dedent(
                """
                import rue
                from rue.resources import resource
                from rue.resources.models import Scope

                @resource(scope=Scope.PROCESS)
                def shared_state():
                    return {"events": []}

                @rue.test.backend("subprocess")
                def test_remote(shared_state):
                    shared_state["events"].append("worker")

                @rue.test
                def test_after(shared_state):
                    assert shared_state["events"] == ["worker"]
                """
            )
        )

        items = materialize_tests(module_path)
        runner = make_runner(null_reporter)
        run = await runner.run(items=items)

        assert run.result.passed == 2, [
            execution.result.error for execution in run.result.executions
        ]
        assert run.result.failed == 0
        assert run.result.errors == 0

    @pytest.mark.asyncio
    async def test_remote_test_scope_generator_teardown_runs_in_parent(
        self,
        tmp_path: Path,
        null_reporter: NullReporter,
    ):
        module_path = tmp_path / "test_remote_parent_teardown.py"
        module_path.write_text(
            dedent(
                """
                import rue
                from rue.resources import resource
                from rue.resources.models import Scope

                @resource(scope=Scope.PROCESS)
                def events():
                    return []

                @resource(scope=Scope.TEST)
                def case_state(events):
                    state = {"events": events}
                    yield state
                    events.append("teardown")

                @rue.test.backend("subprocess")
                def test_remote(case_state):
                    case_state["events"].append("worker")

                @rue.test
                def test_after(events):
                    assert events == ["worker", "teardown"]
                """
            )
        )

        items = materialize_tests(module_path)
        runner = make_runner(null_reporter)
        run = await runner.run(items=items)

        assert run.result.passed == 2, [
            execution.result.error for execution in run.result.executions
        ]
        assert run.result.failed == 0
        assert run.result.errors == 0

    @pytest.mark.asyncio
    async def test_remote_sut_output_is_merged_back_to_parent(
        self,
        tmp_path: Path,
        null_reporter: NullReporter,
    ):
        module_path = tmp_path / "test_remote_sut_output.py"
        module_path.write_text(
            dedent(
                """
                import rue

                class Greeter:
                    def __init__(self) -> None:
                        self.calls = []

                    def greet(self, name: str) -> str:
                        self.calls.append(name)
                        message = f"Hello, {name}!"
                        print(message)
                        return message

                @rue.resource.sut(scope="process")
                def greeter():
                    return rue.SUT(Greeter(), methods=["greet"])

                @rue.test.backend("subprocess")
                def test_remote(greeter):
                    assert greeter.instance.greet("Alice") == "Hello, Alice!"
                    assert greeter.stdout.text == "Hello, Alice!\\n"

                @rue.test
                def test_after(greeter):
                    assert greeter.instance.calls == ["Alice"]
                """
            )
        )

        items = materialize_tests(module_path)
        runner = make_runner(null_reporter)
        run = await runner.run(items=items)

        assert run.result.passed == 2, [
            execution.result.error for execution in run.result.executions
        ]
        assert run.result.failed == 0
        assert run.result.errors == 0
