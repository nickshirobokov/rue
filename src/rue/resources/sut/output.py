"""SUT-owned stdout/stderr capture models and wrapping."""

from __future__ import annotations

import functools
import io
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import TextIO, cast
from uuid import UUID

from rue.resources.sut.models import (
    CapturedEvent,
    CapturedOutput,
    CapturedStream,
    OutputStream,
)


# ---------------------------------------------------------------------------
# Global sys.stdout/stderr interception (singleton)
# ---------------------------------------------------------------------------


type _OutputSink = Callable[[OutputStream, str], None]


class _SysStreamDispatcher(io.TextIOBase):
    """Replacement for sys.stdout/stderr that dispatches to active SUT sinks."""

    def __init__(
        self,
        original: TextIO,
        sinks: ContextVar[tuple[_OutputSink, ...]],
        *,
        is_stdout: bool,
    ) -> None:
        self._original = original
        self._sinks = sinks
        self._stream: OutputStream = "stdout" if is_stdout else "stderr"

    def write(self, s: str) -> int:
        sinks = self._sinks.get()
        if sinks:
            for sink in sinks:
                sink(self._stream, s)
            return len(s)
        self._original.write(s)
        return len(s)

    def flush(self) -> None:
        self._original.flush()

    def writable(self) -> bool:
        return True

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._original.encoding or "utf-8"

    def fileno(self) -> int:
        return self._original.fileno()

    def isatty(self) -> bool:
        return self._original.isatty()


class _SysCaptureManager:
    """Manages global sys.stdout/stderr replacement with dispatchers."""

    def __init__(self) -> None:
        self._sinks: ContextVar[tuple[_OutputSink, ...]] = ContextVar(
            "sut_output_sinks", default=()
        )
        self._original_stdout: TextIO | None = None
        self._original_stderr: TextIO | None = None
        self._depth: int = 0
        self._lock: RLock = RLock()

    @property
    def is_installed(self) -> bool:
        return self._depth > 0

    @contextmanager
    def installed(self) -> Iterator[None]:
        self._install()
        try:
            yield
        finally:
            self._uninstall()

    @contextmanager
    def sink(self, callback: _OutputSink) -> Iterator[None]:
        token = self._sinks.set((*self._sinks.get(), callback))
        try:
            yield
        finally:
            self._sinks.reset(token)

    def _install(self) -> None:
        with self._lock:
            if self._depth == 0:
                original_stdout = sys.stdout
                original_stderr = sys.stderr
                self._original_stdout = original_stdout
                self._original_stderr = original_stderr
                sys.stdout = _SysStreamDispatcher(
                    original_stdout,
                    self._sinks,
                    is_stdout=True,
                )
                sys.stderr = _SysStreamDispatcher(
                    original_stderr,
                    self._sinks,
                    is_stdout=False,
                )
            self._depth += 1

    def _uninstall(self) -> None:
        with self._lock:
            if self._depth == 0:
                return
            self._depth -= 1
            if self._depth > 0:
                return
            if self._original_stdout is not None:
                sys.stdout = self._original_stdout
            if self._original_stderr is not None:
                sys.stderr = self._original_stderr
            self._original_stdout = None
            self._original_stderr = None


_sys_capture = _SysCaptureManager()


# ---------------------------------------------------------------------------
# Per-SUT output capture
# ---------------------------------------------------------------------------


class SUTOutputCapture:
    """Captures stdout and stderr while a wrapped SUT method runs."""

    def __init__(self) -> None:
        self._test_execution_id: ContextVar[UUID | None] = ContextVar(
            f"sut_{id(self)}_output_test_execution_id",
            default=None,
        )
        self._events: ContextVar[list[CapturedEvent] | None] = ContextVar(
            f"sut_{id(self)}_output_events",
            default=None,
        )

    @property
    def output(self) -> CapturedOutput:
        """Return all captured output streams."""
        return CapturedOutput.from_events(self._events_list())

    @property
    def stdout(self) -> CapturedStream:
        """Return captured stdout."""
        return self.output.stdout

    @property
    def stderr(self) -> CapturedStream:
        """Return captured stderr."""
        return self.output.stderr

    def clear(self) -> None:
        """Clear captured output for the current test execution context."""
        self._events_list().clear()

    def reset(self, test_execution_id: UUID | None) -> None:
        """Reset captured output when the test execution changes."""
        if (
            self._test_execution_id.get() == test_execution_id
            and self._events.get() is not None
        ):
            return
        self._test_execution_id.set(test_execution_id)
        self._events.set([])

    def wrap(
        self,
        original_callable: Callable[..., object],
        *,
        is_async: bool,
    ) -> Callable[..., object]:
        """Wrap a SUT callable with output capture."""
        if is_async:

            @functools.wraps(original_callable)
            async def async_wrapped(*args: object, **kwargs: object) -> object:
                with self.capturing():
                    return await cast(
                        "Awaitable[object]",
                        original_callable(*args, **kwargs),
                    )

            return async_wrapped

        @functools.wraps(original_callable)
        def sync_wrapped(*args: object, **kwargs: object) -> object:
            with self.capturing():
                return original_callable(*args, **kwargs)

        return sync_wrapped

    @contextmanager
    def capturing(self) -> Iterator[None]:
        """Capture stdout and stderr within this context."""
        with _sys_capture.installed(), _sys_capture.sink(self._append):
            yield

    @classmethod
    def is_sys_capture_installed(cls) -> bool:
        """Return whether stdout and stderr dispatchers are installed."""
        return _sys_capture.is_installed

    def _append(self, stream: OutputStream, text: str) -> None:
        self._events_list().append(CapturedEvent(stream, text))

    def _events_list(self) -> list[CapturedEvent]:
        events = self._events.get()
        if events is None:
            events = []
            self._events.set(events)
        return events
