"""Lazy, context-scoped process pool for subprocess-backed test execution."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextvars import ContextVar, Token
from types import TracebackType


class LazyProcessPool:
    """Lazily create and bind a subprocess pool for remote test execution."""

    def __init__(self, max_workers: int) -> None:
        self._max_workers = max_workers
        self._pool: ProcessPoolExecutor | None = None
        self._tokens: list[Token[LazyProcessPool | None]] = []

    def __enter__(self) -> LazyProcessPool:
        """Bind this pool holder to the current execution context."""
        self._tokens.append(CURRENT_PROCESS_POOL.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous pool holder and shut down this pool."""
        CURRENT_PROCESS_POOL.reset(self._tokens.pop())
        self.shutdown()

    @classmethod
    def current(cls) -> LazyProcessPool:
        """Return the currently bound lazy process pool."""
        holder = CURRENT_PROCESS_POOL.get()
        if holder is None:
            raise RuntimeError(
                "No active process pool scope. "
                "A subprocess backend was requested outside of Runner.run()."
            )
        return holder

    @classmethod
    def current_executor(cls) -> ProcessPoolExecutor:
        """Return the currently bound executor, creating it if needed."""
        return cls.current().get()

    def get(self) -> ProcessPoolExecutor:
        """Return the executor, creating it on first use."""
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=self._max_workers,
                max_tasks_per_child=1,
            )
        return self._pool

    def shutdown(self) -> None:
        """Shut down the executor if it was created."""
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None


CURRENT_PROCESS_POOL: ContextVar[LazyProcessPool | None] = ContextVar(
    "current_process_pool", default=None
)
