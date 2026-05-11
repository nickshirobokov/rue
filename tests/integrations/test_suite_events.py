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
from rue.context.runtime import CURRENT_SUITE_CONTEXT, SuiteContext
from rue.events import (
    QueueForwarder,
    SessionEventsReceiver,
    SuiteEventsProcessor,
    SuiteEventsReceiver,
)
from rue.experiments.models import ExperimentVariant
from rue.resources import DependencyResolver, registry
from rue.storage import TursoSuiteRecorder, TursoSuiteStore
from rue.testing.compilation import DefaultTestFactory
from rue.testing.execution.suite.executable import ExecutableSuite
from rue.testing.execution.suite.models import ExecutedSuite
from rue.testing.execution.test.models import (
    ExecutedTest,
    TestResult,
    TestStatus,
)
from tests.helpers import make_definition, make_suite_context, materialize_tests


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


class CapturingProcessor(SuiteEventsProcessor):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.suite_execution_id: UUID | None = None

    def configure(self, config) -> None:
        self.events.append(("configure", config.otel))

    async def on_suite_execution_start(self, suite) -> None:
        self.suite_execution_id = suite.suite_execution_id
        self.events.append(("suite_execution_start", suite.suite_execution_id))

    async def on_collection_complete(self, items, suite) -> None:
        self.events.append(("collection_complete", len(items)))
        assert suite.suite_execution_id == self.suite_execution_id

    async def on_tests_ready(self, tests, suite) -> None:
        self.events.append(("tests_ready", len(tests)))
        assert suite.suite_execution_id == self.suite_execution_id

    async def on_di_graphs_compiled(self, graphs) -> None:
        self.events.append(("di_graphs_compiled", len(graphs)))

    async def on_test_execution_start(self, test, suite) -> None:
        self.events.append(("test_execution_start", test.definition.spec.name))
        assert suite.suite_execution_id == self.suite_execution_id

    async def on_test_execution_complete(self, execution, suite) -> None:
        kind = (
            "test_execution_complete"
            if execution.definition.spec.suffix is None
            else "child_test_execution_complete"
        )
        self.events.append((kind, execution.definition.spec.name))
        assert suite.suite_execution_id == self.suite_execution_id

    async def on_suite_execution_complete(self, suite) -> None:
        self.events.append(("suite_execution_complete", suite.suite_execution_id))
        assert suite.suite_execution_id == self.suite_execution_id


class RaisingProcessor(SuiteEventsProcessor):
    async def on_test_execution_complete(self, execution, suite) -> None:
        _ = execution, suite
        raise RuntimeError("processor failed")


class EventNamesProcessor(SuiteEventsProcessor):
    def __init__(self) -> None:
        self.events: list[str] = []

    def configure(self, config) -> None:
        _ = config
        self.events.append("configure")

    async def on_suite_execution_start(self, suite) -> None:
        _ = suite
        self.events.append("on_suite_execution_start")

    async def on_no_tests_found(self, suite) -> None:
        _ = suite
        self.events.append("on_no_tests_found")

    async def on_collection_complete(self, items, suite) -> None:
        _ = items, suite
        self.events.append("on_collection_complete")

    async def on_tests_ready(self, tests, suite) -> None:
        _ = tests, suite
        self.events.append("on_tests_ready")

    async def on_di_graphs_compiled(self, graphs) -> None:
        _ = graphs
        self.events.append("on_di_graphs_compiled")

    async def on_test_execution_start(self, test, suite) -> None:
        _ = test, suite
        self.events.append("on_test_execution_start")

    async def on_test_execution_complete(self, execution, suite) -> None:
        _ = execution, suite
        self.events.append("on_test_execution_complete")

    async def on_suite_stopped_early(self, failure_count, suite) -> None:
        _ = failure_count, suite
        self.events.append("on_suite_stopped_early")

    async def on_suite_execution_complete(self, suite) -> None:
        _ = suite
        self.events.append("on_suite_execution_complete")


class ContextCapturingProcessor(SuiteEventsProcessor):
    def __init__(self) -> None:
        self.variant: ExperimentVariant | None = None
        self.suite_execution_id: UUID | None = None

    async def on_suite_execution_start(self, suite) -> None:
        context = CURRENT_SUITE_CONTEXT.get()
        self.variant = context.experiment_variant
        self.suite_execution_id = suite.suite_execution_id


def test_suite_events_receiver_requires_processor():
    with pytest.raises(ValueError, match="requires at least one processor"):
        SuiteEventsReceiver([])


@pytest.mark.asyncio
async def test_suite_events_receiver_forwards_all_events_to_processors():
    context = make_suite_context(otel=False, bind_events=False)
    processor = EventNamesProcessor()
    item = make_definition("test_forwarded")
    test = DefaultTestFactory().build(item)
    suite = ExecutedSuite(suite_execution_id=context.suite_execution_id)
    execution = ExecutedTest(
        definition=item,
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        test_execution_id=test.test_execution_id,
    )

    with SuiteEventsReceiver([processor]) as receiver:
        await receiver.on_suite_execution_start(suite)
        await receiver.on_no_tests_found()
        await receiver.on_collection_complete([item])
        await receiver.on_tests_ready([test])
        await receiver.on_di_graphs_compiled({})
        await receiver.on_test_execution_start(test)
        await receiver.on_test_execution_complete(execution)
        await receiver.on_suite_stopped_early(1)
        await receiver.on_suite_execution_complete()

    assert processor.events == [
        "configure",
        "on_suite_execution_start",
        "on_no_tests_found",
        "on_collection_complete",
        "on_tests_ready",
        "on_di_graphs_compiled",
        "on_test_execution_start",
        "on_test_execution_complete",
        "on_suite_stopped_early",
        "on_suite_execution_complete",
    ]


@pytest.mark.asyncio
async def test_queue_forwarder_serializes_cloudpickle_only_payload():
    make_suite_context(otel=False, bind_events=False)
    test = DefaultTestFactory().build(make_definition("test_cloudpickle"))
    manager = mp.get_context("spawn").Manager()
    queue = manager.Queue()

    with pytest.raises(AttributeError):
        pickle.dumps(test)

    await QueueForwarder(queue).on_tests_ready([test], ExecutedSuite())
    payload = queue.get(timeout=1)
    event = cloudpickle.loads(payload)
    manager.shutdown()

    assert event.method_name == "on_tests_ready"
    assert event.args[0][0].definition.spec.name == "test_cloudpickle"


@pytest.mark.asyncio
async def test_session_events_receiver_drains_queue_and_restores_context():
    variant = ExperimentVariant(index=3)
    suite_context = SuiteContext(
        config=Config.model_construct(otel=False),
        experiment_variant=variant,
    )
    suite = ExecutedSuite(suite_execution_id=suite_context.suite_execution_id)
    manager = mp.get_context("spawn").Manager()
    queue = manager.Queue()
    processor = ContextCapturingProcessor()
    receiver = SessionEventsReceiver([processor])

    with suite_context:
        forwarder = QueueForwarder(queue)
        await forwarder.on_suite_execution_start(suite)
        forwarder.close()
    await receiver.drain_queue(queue)
    manager.shutdown()

    assert processor.variant == variant
    assert processor.suite_execution_id == suite.suite_execution_id


def test_turso_recorder_is_not_selectable_processor():
    recorder = TursoSuiteRecorder()
    _ = recorder
    assert "TursoSuiteRecorder" not in SuiteEventsProcessor.REGISTRY


def test_custom_processor_autoregisters():
    processor = CapturingProcessor()

    assert SuiteEventsProcessor.REGISTRY["CapturingProcessor"] is processor


@pytest.mark.asyncio
async def test_executable_suite_publishes_suite_events_through_current_receiver(
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
    context = make_suite_context(
        otel=False,
        concurrency=2,
        processors=(processor,),
    )

    suite = await ExecutableSuite(
        items=materialize_tests(module_path),
        suite_execution_id=context.suite_execution_id,
        resolver=DependencyResolver(registry),
    ).execute()

    assert suite.result.passed == 2
    assert processor.events[:5] == [
        ("configure", False),
        ("suite_execution_start", suite.suite_execution_id),
        ("collection_complete", 2),
        ("di_graphs_compiled", 3),
        ("tests_ready", 2),
    ]
    assert [
        event for event in processor.events if event[0] == "test_execution_start"
    ] == [
        ("test_execution_start", "test_iterated"),
        ("test_execution_start", "test_plain"),
    ]
    assert (
        sum(
            1
            for event in processor.events
            if event[0] == "child_test_execution_complete"
        )
        == 2
    )
    assert sorted(
        event for event in processor.events if event[0] == "test_execution_complete"
    ) == [
        ("test_execution_complete", "test_iterated"),
        ("test_execution_complete", "test_plain"),
    ]
    assert processor.events[-1] == (
        "suite_execution_complete",
        suite.suite_execution_id,
    )


@pytest.mark.asyncio
async def test_executable_suite_crashes_without_current_suite_events_receiver(
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

    async def suite_without_receiver() -> None:
        context = make_suite_context(otel=False, bind_events=False)
        await ExecutableSuite(
            items=materialize_tests(module_path),
            suite_execution_id=context.suite_execution_id,
            resolver=DependencyResolver(registry),
        ).execute()

    task = Context().run(asyncio.create_task, suite_without_receiver())
    with pytest.raises(LookupError):
        await task


@pytest.mark.asyncio
async def test_turso_recorder_records_execution_before_suite_finishes(
    database_path: Path,
):
    store = TursoSuiteStore(database_path)
    store.initialize()
    recorder = TursoSuiteRecorder()
    recorder.configure(Config(database_path=database_path))
    suite = ExecutedSuite()
    execution = ExecutedTest(
        definition=make_definition("test_streamed"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        test_execution_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    await recorder.on_suite_execution_start(suite)
    await recorder.on_test_execution_complete(execution, suite)
    recorder.close()

    with store.connection() as conn:
        row = conn.execute(
            "SELECT status FROM test_executions WHERE test_execution_id = ?",
            (str(execution.test_execution_id),),
        ).fetchone()

    assert row["status"] == "passed"


@pytest.mark.asyncio
async def test_turso_recorder_links_child_after_parent_is_persisted(
    database_path: Path,
):
    store = TursoSuiteStore(database_path)
    store.initialize()
    recorder = TursoSuiteRecorder()
    recorder.configure(Config(database_path=database_path))
    suite = ExecutedSuite()
    child = ExecutedTest(
        definition=make_definition("test_child"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        test_execution_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    parent = ExecutedTest(
        definition=make_definition("test_parent"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        test_execution_id=UUID("00000000-0000-0000-0000-000000000003"),
        sub_test_executions=[child],
    )

    await recorder.on_suite_execution_start(suite)
    await recorder.on_test_execution_complete(child, suite)

    with store.connection() as conn:
        parent_id = conn.execute(
            "SELECT parent_id FROM test_executions WHERE test_execution_id = ?",
            (str(child.test_execution_id),),
        ).fetchone()["parent_id"]
    assert parent_id is None

    await recorder.on_test_execution_complete(parent, suite)
    recorder.close()

    with store.connection() as conn:
        linked_parent_id = conn.execute(
            "SELECT parent_id FROM test_executions WHERE test_execution_id = ?",
            (str(child.test_execution_id),),
        ).fetchone()["parent_id"]
    assert linked_parent_id == str(parent.test_execution_id)


@pytest.mark.asyncio
async def test_turso_recorder_keeps_execution_when_later_processor_fails(
    database_path: Path,
):
    store = TursoSuiteStore(database_path)
    store.initialize()
    recorder = TursoSuiteRecorder()
    suite = ExecutedSuite()
    execution = ExecutedTest(
        definition=make_definition("test_before_failure"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        test_execution_id=UUID("00000000-0000-0000-0000-000000000004"),
    )
    make_suite_context(
        database_path=database_path,
        processors=(recorder, RaisingProcessor()),
    )

    await SuiteEventsReceiver.current().on_suite_execution_start(suite)
    with pytest.raises(RuntimeError, match="processor failed"):
        await SuiteEventsReceiver.current().on_test_execution_complete(execution)

    with store.connection() as conn:
        row = conn.execute(
            "SELECT status FROM test_executions WHERE test_execution_id = ?",
            (str(execution.test_execution_id),),
        ).fetchone()
    assert row["status"] == "passed"
