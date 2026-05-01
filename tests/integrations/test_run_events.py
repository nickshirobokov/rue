import asyncio
from contextvars import Context
from pathlib import Path
from textwrap import dedent
from uuid import UUID

import pytest

from rue.events import RunEventsProcessor, RunEventsReceiver
from rue.resources import DependencyResolver, registry
from rue.testing.runner import Runner
from tests.helpers import make_run_context, materialize_tests


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
        self.events.append(("configure", config.db_enabled))

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


def test_run_events_receiver_requires_processor():
    with pytest.raises(ValueError, match="requires at least one processor"):
        RunEventsReceiver([])


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
        db_enabled=False,
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
        event
        for event in processor.events
        if event[0] == "test_start"
    ] == [
        ("test_start", "test_iterated"),
        ("test_start", "test_plain"),
    ]
    assert sum(
        1
        for event in processor.events
        if event[0] == "child_execution_complete"
    ) == 2
    assert sorted(
        event
        for event in processor.events
        if event[0] == "execution_complete"
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
        make_run_context(otel=False, db_enabled=False, bind_events=False)
        await Runner().run(
            items=materialize_tests(module_path),
            resolver=DependencyResolver(registry),
        )

    task = Context().run(asyncio.create_task, run_without_receiver())
    with pytest.raises(LookupError):
        await task
