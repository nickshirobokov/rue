import time
from pathlib import Path
from textwrap import dedent

import pytest

from rue.events import RunEventsProcessor
from rue.resources import DependencyResolver, registry
from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.runner import Runner
from tests.helpers import make_run_context, materialize_tests


class QueueOrderProcessor(RunEventsProcessor):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def on_test_start(self, test, run) -> None:
        _ = run
        self.events.append(("start", test.definition.spec.full_name))

    async def on_execution_complete(self, execution, run) -> None:
        _ = run
        kind = (
            "complete"
            if execution.definition.spec.suffix is None
            else "complete_child"
        )
        self.events.append((kind, execution.definition.spec.full_name))


def _event_index(
    events: list[tuple[str, str]], kind: str, name: str
) -> int:
    return events.index((kind, name))


def _full_name(module_path: Path, name: str) -> str:
    return f"{module_path.stem}::test_{name}"


def _materialize_paths(*paths: Path):
    collection = TestSpecCollector((), (), None).build_spec_collection(paths)
    return TestLoader(collection.suite_root).load_from_collection(collection)


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

    expected_order = [_full_name(module_path, name) for name in "ABCDEFGHIJKL"]
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
    processor = QueueOrderProcessor()

    make_run_context(
        otel=False,
        concurrency=4,
        processors=(processor,),
    )
    run = await Runner().run(items=items, resolver=DependencyResolver(registry))

    assert run.result.passed == len(expected_order), [
        (
            execution.definition.spec.name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]

    assert [
        name for kind, name in processor.events if kind == "start"
    ] == expected_order
    assert [
        execution.definition.spec.full_name
        for execution in run.result.executions
    ] == expected_order
    assert {
        execution.definition.spec.name: len(execution.sub_executions)
        for execution in run.result.executions
        if execution.definition.spec.name in expected_subtest_counts
    } == expected_subtest_counts

    a_complete = _event_index(
        processor.events, "complete", _full_name(module_path, "A")
    )
    assert all(
        a_complete < _event_index(processor.events, "start", name)
        for name in (
            _full_name(module_path, "B"),
            _full_name(module_path, "C"),
            _full_name(module_path, "D"),
        )
    )

    e_start = _event_index(
        processor.events, "start", _full_name(module_path, "E")
    )
    assert all(
        _event_index(processor.events, "complete", name) < e_start
        for name in (
            _full_name(module_path, "B"),
            _full_name(module_path, "C"),
            _full_name(module_path, "D"),
        )
    )

    f_start = _event_index(
        processor.events, "start", _full_name(module_path, "F")
    )
    assert (
        _event_index(processor.events, "complete", _full_name(module_path, "E"))
        < f_start
    )

    g_start = _event_index(
        processor.events, "start", _full_name(module_path, "G")
    )
    assert (
        _event_index(processor.events, "complete", _full_name(module_path, "F"))
        < g_start
    )

    h_group_starts = [
        _event_index(processor.events, "start", name)
        for name in (
            _full_name(module_path, "H"),
            _full_name(module_path, "I"),
            _full_name(module_path, "J"),
        )
    ]
    assert all(
        _event_index(processor.events, "complete", _full_name(module_path, "G"))
        < index
        for index in h_group_starts
    )

    k_start = _event_index(
        processor.events, "start", _full_name(module_path, "K")
    )
    assert all(
        _event_index(processor.events, "complete", name) < k_start
        for name in (
            _full_name(module_path, "H"),
            _full_name(module_path, "I"),
            _full_name(module_path, "J"),
        )
    )

    l_start = _event_index(
        processor.events, "start", _full_name(module_path, "L")
    )
    assert (
        _event_index(processor.events, "complete", _full_name(module_path, "K"))
        < l_start
    )


@pytest.mark.asyncio
async def test_runner_executes_multiple_modules_in_queue_order(
    tmp_path: Path,
):
    module_a1_path = tmp_path / "test_a1.py"
    module_a2_path = tmp_path / "test_a2.py"
    module_a1_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            def test_A():
                time.sleep(0.05)

            @rue.test
            async def test_B():
                await asyncio.sleep(0.04)

            @rue.test
            async def test_C():
                await asyncio.sleep(0.02)

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_D():
                time.sleep(0.03)

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            def test_E():
                time.sleep(0.01)

            @rue.test
            async def test_F():
                await asyncio.sleep(0.02)

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            def test_G():
                time.sleep(0.01)

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_H():
                time.sleep(0.05)

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_I():
                time.sleep(0.01)

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_J():
                time.sleep(0.03)

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            def test_K():
                time.sleep(0.01)

            @rue.test
            async def test_L():
                await asyncio.sleep(0.03)
            """
        )
    )
    module_a2_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend

            @rue.test
            async def test_A():
                await asyncio.sleep(0.01)

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            def test_B():
                time.sleep(0.01)

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            def test_C():
                time.sleep(0.01)

            @rue.test.backend(ExecutionBackend.SUBPROCESS)
            def test_D():
                time.sleep(0.02)
            """
        )
    )

    expected_order = [
        *(_full_name(module_a1_path, name) for name in "ABCDEFGHIJKL"),
        *(_full_name(module_a2_path, name) for name in "ABCD"),
    ]
    items = _materialize_paths(module_a1_path, module_a2_path)
    processor = QueueOrderProcessor()

    make_run_context(
        otel=False,
        concurrency=4,
        processors=(processor,),
    )
    run = await Runner().run(items=items, resolver=DependencyResolver(registry))

    assert run.result.passed == len(expected_order), [
        (
            execution.definition.spec.full_name,
            execution.status.value,
            str(execution.result.error) if execution.result.error else None,
        )
        for execution in run.result.executions
    ]

    assert [
        execution.definition.spec.full_name
        for execution in run.result.executions
    ] == expected_order

    a1_a_complete = _event_index(
        processor.events, "complete", _full_name(module_a1_path, "A")
    )
    a2_a_start = _event_index(
        processor.events, "start", _full_name(module_a2_path, "A")
    )
    assert a2_a_start < a1_a_complete

    a2_b_start = _event_index(
        processor.events, "start", _full_name(module_a2_path, "B")
    )
    assert a2_b_start < a1_a_complete

    a1_b_complete = _event_index(
        processor.events, "complete", _full_name(module_a1_path, "B")
    )
    a1_d_complete = _event_index(
        processor.events, "complete", _full_name(module_a1_path, "D")
    )
    a2_d_start = _event_index(
        processor.events, "start", _full_name(module_a2_path, "D")
    )
    assert a2_d_start < max(a1_b_complete, a1_d_complete)

    a1_e_start = _event_index(
        processor.events, "start", _full_name(module_a1_path, "E")
    )
    assert a2_d_start < a1_e_start


@pytest.mark.asyncio
async def test_runner_keeps_global_main_as_absolute_barrier_across_modules(
    tmp_path: Path,
):
    module_a1_path = tmp_path / "test_global_a1.py"
    module_a2_path = tmp_path / "test_global_a2.py"
    module_a1_path.write_text(
        dedent(
            """
            import asyncio
            import time

            import rue
            from rue import ExecutionBackend

            @rue.test
            async def test_A():
                await asyncio.sleep(0.04)

            @rue.test.backend(ExecutionBackend.MAIN)
            def test_B():
                time.sleep(0.02)
            """
        )
    )
    module_a2_path.write_text(
        dedent(
            """
            import asyncio

            import rue

            @rue.test
            async def test_A():
                await asyncio.sleep(0.02)

            @rue.test
            async def test_B():
                await asyncio.sleep(0.01)
            """
        )
    )

    items = _materialize_paths(module_a1_path, module_a2_path)
    processor = QueueOrderProcessor()

    make_run_context(
        otel=False,
        concurrency=2,
        processors=(processor,),
    )
    run = await Runner().run(items=items, resolver=DependencyResolver(registry))

    assert run.result.passed == 4

    main_start = _event_index(
        processor.events, "start", _full_name(module_a1_path, "B")
    )
    main_complete = _event_index(
        processor.events, "complete", _full_name(module_a1_path, "B")
    )
    assert _event_index(
        processor.events, "complete", _full_name(module_a1_path, "A")
    ) < main_start
    assert main_complete < _event_index(
        processor.events, "start", _full_name(module_a2_path, "A")
    )
    assert main_complete < _event_index(
        processor.events, "start", _full_name(module_a2_path, "B")
    )


@pytest.mark.asyncio
async def test_module_main_keeps_iterate_children_concurrent(
    tmp_path: Path,
):
    module_path = tmp_path / "test_module_main_iterate.py"
    module_path.write_text(
        dedent(
            """
            import time

            import rue
            from rue import ExecutionBackend

            @rue.test.backend(ExecutionBackend.MODULE_MAIN)
            @rue.test.iterate.params("pause", [0.2, 0.12, 0.16])
            def test_A(pause):
                time.sleep(pause)
            """
        )
    )

    items = materialize_tests(module_path)

    start = time.perf_counter()
    make_run_context(
        otel=False,
        concurrency=3,
    )
    run = await Runner().run(items=items, resolver=DependencyResolver(registry))
    duration = time.perf_counter() - start

    assert run.result.passed == 1
    assert duration < 0.32
