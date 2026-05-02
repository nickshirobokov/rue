import asyncio
import sqlite3
from contextvars import Context
from pathlib import Path
from textwrap import dedent
from uuid import UUID

import pytest

from rue.config import Config
from rue.events import RunEventsProcessor, RunEventsReceiver
from rue.resources import DependencyResolver, registry
from rue.storage import DBManager, DBWriter
from rue.testing.models import ExecutedTest, Run, TestResult, TestStatus
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


def test_run_events_receiver_requires_processor():
    with pytest.raises(ValueError, match="requires at least one processor"):
        RunEventsReceiver([])


def test_db_writer_is_not_selectable_processor():
    writer = DBWriter()
    _ = writer
    assert "DBWriter" not in RunEventsProcessor.REGISTRY


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
async def test_db_writer_records_execution_before_run_finishes(
    sqlite_db_path: Path,
):
    manager = DBManager(sqlite_db_path)
    manager.initialize()
    writer = DBWriter()
    writer.configure(Config(db_path=sqlite_db_path))
    run = Run()
    execution = ExecutedTest(
        definition=make_definition("test_streamed"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    await writer.on_run_start(run)
    await writer.on_execution_complete(execution, run)

    with sqlite3.connect(sqlite_db_path) as conn:
        row = conn.execute(
            "SELECT status FROM test_executions WHERE execution_id = ?",
            (str(execution.execution_id),),
        ).fetchone()

    assert row == ("passed",)


@pytest.mark.asyncio
async def test_db_writer_links_child_after_parent_is_persisted(
    sqlite_db_path: Path,
):
    manager = DBManager(sqlite_db_path)
    manager.initialize()
    writer = DBWriter()
    writer.configure(Config(db_path=sqlite_db_path))
    run = Run()
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

    await writer.on_run_start(run)
    await writer.on_execution_complete(child, run)

    with sqlite3.connect(sqlite_db_path) as conn:
        parent_id = conn.execute(
            "SELECT parent_id FROM test_executions WHERE execution_id = ?",
            (str(child.execution_id),),
        ).fetchone()[0]
    assert parent_id is None

    await writer.on_execution_complete(parent, run)

    with sqlite3.connect(sqlite_db_path) as conn:
        linked_parent_id = conn.execute(
            "SELECT parent_id FROM test_executions WHERE execution_id = ?",
            (str(child.execution_id),),
        ).fetchone()[0]
    assert linked_parent_id == str(parent.execution_id)


@pytest.mark.asyncio
async def test_db_writer_keeps_execution_when_later_processor_fails(
    sqlite_db_path: Path,
):
    manager = DBManager(sqlite_db_path)
    manager.initialize()
    writer = DBWriter()
    run = Run()
    execution = ExecutedTest(
        definition=make_definition("test_before_failure"),
        result=TestResult(status=TestStatus.PASSED, duration_ms=1.0),
        execution_id=UUID("00000000-0000-0000-0000-000000000004"),
    )
    make_run_context(
        db_path=sqlite_db_path,
        processors=(writer, RaisingProcessor()),
    )

    await RunEventsReceiver.current().on_run_start(run)
    with pytest.raises(RuntimeError, match="processor failed"):
        await RunEventsReceiver.current().on_execution_complete(execution)

    with sqlite3.connect(sqlite_db_path) as conn:
        row = conn.execute(
            "SELECT status FROM test_executions WHERE execution_id = ?",
            (str(execution.execution_id),),
        ).fetchone()
    assert row == ("passed",)
