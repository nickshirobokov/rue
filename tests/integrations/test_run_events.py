import asyncio
import multiprocessing as mp
import pickle
from contextvars import Context
from pathlib import Path
from textwrap import dedent
from uuid import UUID

import cloudpickle
import pytest

from rue.config import Config
from rue.context.runtime import CURRENT_RUN_CONTEXT, RunContext
from rue.events import (
    QueueForwarder,
    RunEventsProcessor,
    RunEventsReceiver,
    SessionEventsReceiver,
)
from rue.experiments.models import ExperimentVariant
from rue.resources import DependencyResolver, registry
from rue.storage import TursoRunRecorder, TursoRunStore
from rue.testing.execution.factory import DefaultTestFactory
from rue.testing.models import ExecutedRun, ExecutedTest, TestResult, TestStatus
from rue.testing.runner import Runner
from tests.helpers import make_definition, make_run_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


class CapturingProcessor(RunEventsProcessor):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.run_id: UUID | None = None

    def configure(self, config) -> None:
        self.events.append(("configure", config.otel))

    async def on_run_start(self, run) -> None:
        self.run_id = run.run_id
        self.events.append(("run_start", run.run_id))

    async def on_collection_complete(self, items, run) -> None:
        self.events.append(("collection_complete", len(items)))
        assert run.run_id == self.run_id

    async def on_tests_ready(self, tests, run) -> None:
        self.events.append(("tests_ready", len(tests)))
        assert run.run_id == self.run_id

    async def on_di_graphs_compiled(self, graphs) -> None:
        self.events.append(("di_graphs_compiled", len(graphs)))

    async def on_test_start(self, test, run) -> None:
        self.events.append(("test_start", test.definition.spec.name))
        assert run.run_id == self.run_id

    async def on_execution_complete(self, execution, run) -> None:
        kind = (
            "execution_complete"
            if execution.definition.spec.suffix is None
            else "child_execution_complete"
        )
        self.events.append((kind, execution.definition.spec.name))
        assert run.run_id == self.run_id

    async def on_run_complete(self, run) -> None:
        self.events.append(("run_complete", run.run_id))
        assert run.run_id == self.run_id


class RaisingProcessor(RunEventsProcessor):
    async def on_execution_complete(self, execution, run) -> None:
        _ = execution, run
        raise RuntimeError("processor failed")


class EventNamesProcessor(RunEventsProcessor):
    def __init__(self) -> None:
        self.events: list[str] = []

    def configure(self, config) -> None:
        _ = config
        self.events.append("configure")

    async def on_run_start(self, run) -> None:
        _ = run
        self.events.append("on_run_start")

    async def on_no_tests_found(self, run) -> None:
        _ = run
        self.events.append("on_no_tests_found")

    async def on_collection_complete(self, items, run) -> None:
        _ = items, run
        self.events.append("on_collection_complete")

    async def on_tests_ready(self, tests, run) -> None:
        _ = tests, run
        self.events.append("on_tests_ready")

    async def on_di_graphs_compiled(self, graphs) -> None:
        _ = graphs
        self.events.append("on_di_graphs_compiled")

    async def on_test_start(self, test, run) -> None:
        _ = test, run
        self.events.append("on_test_start")

    async def on_execution_complete(self, execution, run) -> None:
        _ = execution, run
        self.events.append("on_execution_complete")

    async def on_run_stopped_early(self, failure_count, run) -> None:
        _ = failure_count, run
        self.events.append("on_run_stopped_early")

    async def on_run_complete(self, run) -> None:
        _ = run
        self.events.append("on_run_complete")


class ContextCapturingProcessor(RunEventsProcessor):
    def __init__(self) -> None:
        self.variant: ExperimentVariant | None = None
        self.run_id: UUID | None = None

    async def on_run_start(self, run) -> None:
        context = CURRENT_RUN_CONTEXT.get()
        self.variant = context.experiment_variant
        self.run_id = run.run_id


def test_run_events_receiver_requires_processor():
    with pytest.raises(ValueError, match="requires at least one processor"):
        RunEventsReceiver([])


@pytest.mark.asyncio
async def test_run_events_receiver_forwards_all_events_to_processors():
    context = make_run_context(otel=False, bind_events=False)
    processor = EventNamesProcessor()
    item = make_definition("test_forwarded")
    test = DefaultTestFactory().build(item)
    run = ExecutedRun(run_id=context.run_id)
    execution = ExecutedTest(
        definition=item,
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=test.execution_id,
    )

    with RunEventsReceiver([processor]) as receiver:
        await receiver.on_run_start(run)
        await receiver.on_no_tests_found()
        await receiver.on_collection_complete([item])
        await receiver.on_tests_ready([test])
        await receiver.on_di_graphs_compiled({})
        await receiver.on_test_start(test)
        await receiver.on_execution_complete(execution)
        await receiver.on_run_stopped_early(1)
        await receiver.on_run_complete()

    assert processor.events == [
        "configure",
        "on_run_start",
        "on_no_tests_found",
        "on_collection_complete",
        "on_tests_ready",
        "on_di_graphs_compiled",
        "on_test_start",
        "on_execution_complete",
        "on_run_stopped_early",
        "on_run_complete",
    ]


@pytest.mark.asyncio
async def test_queue_forwarder_serializes_cloudpickle_only_payload():
    make_run_context(otel=False, bind_events=False)
    test = DefaultTestFactory().build(make_definition("test_cloudpickle"))
    manager = mp.get_context("spawn").Manager()
    queue = manager.Queue()

    with pytest.raises(AttributeError):
        pickle.dumps(test)

    await QueueForwarder(queue).on_tests_ready([test], ExecutedRun())
    payload = queue.get(timeout=1)
    event = cloudpickle.loads(payload)
    manager.shutdown()

    assert event.method_name == "on_tests_ready"
    assert event.args[0][0].definition.spec.name == "test_cloudpickle"


@pytest.mark.asyncio
async def test_session_events_receiver_drains_queue_and_restores_context():
    variant = ExperimentVariant(index=3)
    run_context = RunContext(
        config=Config.model_construct(otel=False),
        experiment_variant=variant,
    )
    run = ExecutedRun(run_id=run_context.run_id)
    manager = mp.get_context("spawn").Manager()
    queue = manager.Queue()
    processor = ContextCapturingProcessor()
    receiver = SessionEventsReceiver([processor])

    with run_context:
        forwarder = QueueForwarder(queue)
        await forwarder.on_run_start(run)
        forwarder.close()
    await receiver.drain_queue(queue)
    manager.shutdown()

    assert processor.variant == variant
    assert processor.run_id == run.run_id


def test_turso_recorder_is_not_selectable_processor():
    recorder = TursoRunRecorder()
    _ = recorder
    assert "TursoRunRecorder" not in RunEventsProcessor.REGISTRY


def test_custom_processor_autoregisters():
    processor = CapturingProcessor()

    assert RunEventsProcessor.REGISTRY["CapturingProcessor"] is processor


@pytest.mark.asyncio
async def test_runner_publishes_run_events_through_current_receiver(
    tmp_path: Path,
):
    module_path = tmp_path / "test_events.py"
    module_path.write_text(
        dedent(
            """
            import rue

            @rue.test.iterate.params("value", [1, 2])
            @rue.test
            def test_iterated(value):
                assert value

            @rue.test
            def test_plain():
                assert True
            """
        )
    )
    processor = CapturingProcessor()
    make_run_context(
        otel=False,
        concurrency=2,
        processors=(processor,),
    )

    run = await Runner().run(
        items=materialize_tests(module_path),
        resolver=DependencyResolver(registry),
    )

    assert run.result.passed == 2
    assert processor.events[:5] == [
        ("configure", False),
        ("run_start", run.run_id),
        ("collection_complete", 2),
        ("di_graphs_compiled", 3),
        ("tests_ready", 2),
    ]
    assert [
        event for event in processor.events if event[0] == "test_start"
    ] == [
        ("test_start", "test_iterated"),
        ("test_start", "test_plain"),
    ]
    assert (
        sum(
            1
            for event in processor.events
            if event[0] == "child_execution_complete"
        )
        == 2
    )
    assert sorted(
        event for event in processor.events if event[0] == "execution_complete"
    ) == [
        ("execution_complete", "test_iterated"),
        ("execution_complete", "test_plain"),
    ]
    assert processor.events[-1] == ("run_complete", run.run_id)


@pytest.mark.asyncio
async def test_runner_crashes_without_current_run_events_receiver(
    tmp_path: Path,
):
    module_path = tmp_path / "test_missing_receiver.py"
    module_path.write_text(
        dedent(
            """
            import rue

            @rue.test
            def test_plain():
                assert True
            """
        )
    )

    async def run_without_receiver() -> None:
        make_run_context(otel=False, bind_events=False)
        await Runner().run(
            items=materialize_tests(module_path),
            resolver=DependencyResolver(registry),
        )

    task = Context().run(asyncio.create_task, run_without_receiver())
    with pytest.raises(LookupError):
        await task


@pytest.mark.asyncio
async def test_turso_recorder_records_execution_before_run_finishes(
    database_path: Path,
):
    store = TursoRunStore(database_path)
    store.initialize()
    recorder = TursoRunRecorder()
    recorder.configure(Config(database_path=database_path))
    run = ExecutedRun()
    execution = ExecutedTest(
        definition=make_definition("test_streamed"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    await recorder.on_run_start(run)
    await recorder.on_execution_complete(execution, run)
    recorder.close()

    with store.connection() as conn:
        row = conn.execute(
            "SELECT status FROM executions WHERE execution_id = ?",
            (str(execution.execution_id),),
        ).fetchone()

    assert row["status"] == "passed"


@pytest.mark.asyncio
async def test_turso_recorder_links_child_after_parent_is_persisted(
    database_path: Path,
):
    store = TursoRunStore(database_path)
    store.initialize()
    recorder = TursoRunRecorder()
    recorder.configure(Config(database_path=database_path))
    run = ExecutedRun()
    child = ExecutedTest(
        definition=make_definition("test_child"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    parent = ExecutedTest(
        definition=make_definition("test_parent"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=UUID("00000000-0000-0000-0000-000000000003"),
        sub_executions=[child],
    )

    await recorder.on_run_start(run)
    await recorder.on_execution_complete(child, run)

    with store.connection() as conn:
        parent_id = conn.execute(
            "SELECT parent_id FROM executions WHERE execution_id = ?",
            (str(child.execution_id),),
        ).fetchone()["parent_id"]
    assert parent_id is None

    await recorder.on_execution_complete(parent, run)
    recorder.close()

    with store.connection() as conn:
        linked_parent_id = conn.execute(
            "SELECT parent_id FROM executions WHERE execution_id = ?",
            (str(child.execution_id),),
        ).fetchone()["parent_id"]
    assert linked_parent_id == str(parent.execution_id)


@pytest.mark.asyncio
async def test_turso_recorder_keeps_execution_when_later_processor_fails(
    database_path: Path,
):
    store = TursoRunStore(database_path)
    store.initialize()
    recorder = TursoRunRecorder()
    run = ExecutedRun()
    execution = ExecutedTest(
        definition=make_definition("test_before_failure"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=UUID("00000000-0000-0000-0000-000000000004"),
    )
    make_run_context(
        database_path=database_path,
        processors=(recorder, RaisingProcessor()),
    )

    await RunEventsReceiver.current().on_run_start(run)
    with pytest.raises(RuntimeError, match="processor failed"):
        await RunEventsReceiver.current().on_execution_complete(execution)

    with store.connection() as conn:
        row = conn.execute(
            "SELECT status FROM executions WHERE execution_id = ?",
            (str(execution.execution_id),),
        ).fetchone()
    assert row["status"] == "passed"
