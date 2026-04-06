"""Tests for run_inline decorator and threaded sync execution."""

import asyncio
import threading
from pathlib import Path

from rue.testing import Runner, run_inline
from rue.testing.models import RepeatModifier, TestItem


def test_sync_test_runs_in_worker_thread(null_reporter):
    runner = Runner(reporters=[null_reporter])
    observed_thread = None

    def test_check_thread():
        nonlocal observed_thread
        observed_thread = threading.current_thread()

    item = TestItem(
        name="test_check_thread",
        fn=test_check_thread,
        module_path=Path("sample.py"),
        is_async=False,
        params=[],
    )

    asyncio.run(runner.run(items=[item]))

    assert observed_thread is not None
    assert observed_thread is not threading.main_thread()


def test_run_inline_test_runs_on_main_thread(null_reporter):
    runner = Runner(reporters=[null_reporter])
    observed_thread = None

    @run_inline
    def test_inline():
        nonlocal observed_thread
        observed_thread = threading.current_thread()

    item = TestItem(
        name="test_inline",
        fn=test_inline,
        module_path=Path("sample.py"),
        is_async=False,
        params=[],
        run_inline=True,
    )

    asyncio.run(runner.run(items=[item]))

    assert observed_thread is not None
    assert observed_thread is threading.main_thread()


def test_sync_exception_propagates(null_reporter):
    runner = Runner(reporters=[null_reporter])

    def test_raise():
        raise ValueError("sync boom")

    item = TestItem(
        name="test_raise",
        fn=test_raise,
        module_path=Path("sample.py"),
        is_async=False,
        params=[],
    )

    run_result = asyncio.run(runner.run(items=[item]))

    assert run_result.result.failed == 0
    assert run_result.result.errors == 1
    execution = run_result.result.executions[0]
    assert isinstance(execution.result.error, ValueError)
    assert "sync boom" in str(execution.result.error)


def test_run_inline_propagates_through_repeat(null_reporter):
    runner = Runner(reporters=[null_reporter])
    threads: list[threading.Thread] = []

    @run_inline
    def test_inline_repeat():
        threads.append(threading.current_thread())

    item = TestItem(
        name="test_inline_repeat",
        fn=test_inline_repeat,
        module_path=Path("sample.py"),
        is_async=False,
        params=[],
        run_inline=True,
        modifiers=[RepeatModifier(count=3, min_passes=3)],
    )

    asyncio.run(runner.run(items=[item]))

    assert len(threads) == 3
    assert all(t is threading.main_thread() for t in threads)
