"""Example demonstrating sync test threading and queue barrier backends.

By default, sync rue tests run in a worker thread so the event loop
stays responsive (e.g. for live console updates). Use
@rue.test.backend(ExecutionBackend.MODULE_MAIN)
when a test should block only its own module queue, and
@rue.test.backend(ExecutionBackend.MAIN)
when a test must execute on the true main thread and block all work.

    uv run rue test examples/test_example_run_inline.py -v
"""

import threading
import time

import rue
from rue import ExecutionBackend


@rue.test
def test_sync_default():
    """This sync test runs in a worker thread (default behavior)."""
    time.sleep(0.2)
    assert threading.current_thread() is not threading.main_thread()


@rue.test.backend(ExecutionBackend.MAIN)
def test_sync_inline():
    """This sync test runs on the main event-loop thread."""
    assert threading.current_thread() is threading.main_thread()


@rue.test.backend(ExecutionBackend.MODULE_MAIN)
def test_sync_module_barrier():
    """This sync test stays on a worker thread and blocks only this module."""
    time.sleep(0.1)
    assert threading.current_thread() is not threading.main_thread()


@rue.test
async def test_async_unaffected():
    """Async tests are always awaited on the event loop — no change."""
    assert threading.current_thread() is threading.main_thread()


@rue.test.iterate(3)
def test_sync_repeated():
    """Repeated sync tests also run in worker threads by default."""
    time.sleep(0.1)
    assert threading.current_thread() is not threading.main_thread()


@rue.test.backend(ExecutionBackend.MAIN)
@rue.test.iterate(3)
def test_inline_repeated():
    """Repeated MAIN tests stay on the main thread and block other work."""
    time.sleep(0.1)
    assert threading.current_thread() is threading.main_thread()
