"""Lazy, context-scoped process pool for subprocess-backed test execution."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar


class LazyProcessPool:
    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None

    def get(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_tasks_per_child=1)
        return self._pool

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None


CURRENT_PROCESS_POOL: ContextVar[LazyProcessPool | None] = ContextVar(
    "current_process_pool", default=None
)


@contextmanager
def process_pool_scope() -> Iterator[LazyProcessPool]:
    holder = LazyProcessPool()
    token = CURRENT_PROCESS_POOL.set(holder)
    try:
        yield holder
    finally:
        CURRENT_PROCESS_POOL.reset(token)
        holder.shutdown()


def get_process_pool() -> ProcessPoolExecutor:
    holder = CURRENT_PROCESS_POOL.get()
    if holder is None:
        raise RuntimeError(
            "No active process pool scope. "
            "A subprocess backend was requested outside of Runner.run()."
        )
    return holder.get()
