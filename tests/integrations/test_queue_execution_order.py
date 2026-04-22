from pathlib import Path
from textwrap import dedent

import pytest

from rue.config import Config
from rue.testing.runner import Runner
from tests.unit.conftest import NullReporter
from tests.unit.factories import materialize_tests


class QueueOrderReporter(NullReporter):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def on_test_start(self, item) -> None:
        self.events.append(("start", item.spec.name))

    async def on_execution_complete(self, execution) -> None:
        kind = (
            "complete"
            if execution.definition.spec.suffix is None
            else "complete_child"
        )
        self.events.append((kind, execution.definition.spec.name))


def _event_index(
    events: list[tuple[str, str]], kind: str, name: str
) -> int:
    return events.index((kind, name))


@pytest.mark.asyncio
async def test_runner_executes_mixed_backends_in_queue_order(
    tmp_path: Path,
):
    module_path = tmp_path / "test_queue_execution_order_module.py"
    module_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_A():
                time.sleep(0.01)

            @rue.test.iterate.params("pause", [0.12, 0.03, 0.06])
            @rue.test
            async def test_B(pause):
                await asyncio.sleep(pause)

            @rue.test.iterate.params("pause", [0.02, 0.05, 0.01, 0.04])
            @rue.test
            async def test_C(pause):
                await asyncio.sleep(pause)

            @rue.test.iterate.params("pause", [0.07, 0.02, 0.05, 0.03, 0.04])
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_D(pause):
                time.sleep(pause)

            @rue.test.backend(ExecutionBackend.MAIN)
            @rue.test.iterate.params("pause", [0.01, 0.02, 0.01, 0.03])
            def test_E(pause):
                time.sleep(pause)

            @rue.test.iterate.params("pause", [0.03, 0.01, 0.02])
            @rue.test
            async def test_F(pause):
                await asyncio.sleep(pause)

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_G():
                time.sleep(0.01)

            @rue.test.iterate.params("pause", [0.11, 0.04, 0.08, 0.02])
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_H(pause):
                time.sleep(pause)

            @rue.test.iterate.params("pause", [0.04, 0.01, 0.03, 0.02, 0.05])
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_I(pause):
                time.sleep(pause)

            @rue.test.iterate.params("pause", [0.08, 0.02, 0.05])
            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_J(pause):
                time.sleep(pause)

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_K():
                time.sleep(0.01)

            @rue.test.iterate.params("pause", [0.02, 0.01, 0.03, 0.04])
            @rue.test
            async def test_L(pause):
                await asyncio.sleep(pause)
            """
        )
    )

    expected_order = [f"test_{name}" for name in "ABCDEFGHIJKL"]
    expected_subtest_counts = {
        "test_B": 3,
        "test_C": 4,
        "test_D": 5,
        "test_E": 4,
        "test_F": 3,
        "test_H": 4,
        "test_I": 5,
        "test_J": 3,
        "test_L": 4,
    }
    items = materialize_tests(module_path)
    reporter = QueueOrderReporter()

    run = await Runner(
        config=Config.model_construct(
            otel=False,
            db_enabled=False,
            concurrency=4,
        ),
        reporters=[reporter],
    ).run(items=items)

    assert run.result.passed == len(expected_order), [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]

    assert [
        name for kind, name in reporter.events if kind == "start"
    ] == expected_order
    assert [
        execution.definition.spec.name for execution in run.result.executions
    ] == expected_order
    assert {
        execution.definition.spec.name: len(execution.sub_executions)
        for execution in run.result.executions
        if execution.definition.spec.name in expected_subtest_counts
    } == expected_subtest_counts

    a_complete = _event_index(reporter.events, "complete", "test_A")
    assert all(
        a_complete < _event_index(reporter.events, "start", name)
        for name in ("test_B", "test_C", "test_D")
    )

    e_start = _event_index(reporter.events, "start", "test_E")
    assert all(
        _event_index(reporter.events, "complete", name) < e_start
        for name in ("test_B", "test_C", "test_D")
    )

    f_start = _event_index(reporter.events, "start", "test_F")
    assert _event_index(reporter.events, "complete", "test_E") < f_start

    g_start = _event_index(reporter.events, "start", "test_G")
    assert _event_index(reporter.events, "complete", "test_F") < g_start

    h_group_starts = [
        _event_index(reporter.events, "start", name)
        for name in ("test_H", "test_I", "test_J")
    ]
    assert all(
        _event_index(reporter.events, "complete", "test_G") < index
        for index in h_group_starts
    )

    k_start = _event_index(reporter.events, "start", "test_K")
    assert all(
        _event_index(reporter.events, "complete", name) < k_start
        for name in ("test_H", "test_I", "test_J")
    )

    l_start = _event_index(reporter.events, "start", "test_L")
    assert _event_index(reporter.events, "complete", "test_K") < l_start
