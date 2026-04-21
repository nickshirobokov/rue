"""SUT-owned stdout/stderr capture models and wrapping."""

from __future__ import annotations

import functools
import io
import sys
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Literal, TextIO, cast
from uuid import UUID


type OutputStream = Literal["stdout", "stderr"]
type _OutputSink = Callable[[OutputStream, str], None]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapturedEvent:
    stream: OutputStream
    text: str


@dataclass(frozen=True, slots=True)
class CapturedStream:
    text: str

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.text.splitlines())


@dataclass(frozen=True, slots=True)
class CapturedOutput:
    stdout: CapturedStream
    stderr: CapturedStream
    combined: CapturedStream
    events: tuple[CapturedEvent, ...]

    @classmethod
    def from_events(cls, events: Sequence[CapturedEvent]) -> CapturedOutput:
        events_tuple = tuple(events)
        stdout = "".join(e.text for e in events_tuple if e.stream == "stdout")
        stderr = "".join(e.text for e in events_tuple if e.stream == "stderr")
        combined = "".join(e.text for e in events_tuple)
        return cls(
            stdout=CapturedStream(stdout),
            stderr=CapturedStream(stderr),
            combined=CapturedStream(combined),
            events=events_tuple,
        )


# ---------------------------------------------------------------------------
# Global sys.stdout/stderr interception (singleton)
# ---------------------------------------------------------------------------


class _SysStreamDispatcher(io.TextIOBase):
    """Replacement for sys.stdout/stderr that dispatches to active SUT sinks."""

    def __init__(
        self,
        original: TextIO,
        sinks: ContextVar[tuple[_OutputSink, ...]],
        swallow: ContextVar[bool],
        manager: _SysCaptureManager,
        *,
        is_stdout: bool,
    ) -> None:
        self._original = original
        self._sinks = sinks
        self._swallow = swallow
        self._manager = manager
        self._stream: OutputStream = "stdout" if is_stdout else "stderr"

    def write(self, s: str) -> int:
        sinks = self._sinks.get()
        if sinks:
            for sink in sinks:
                sink(self._stream, s)
            if self._swallow.get():
                return len(s)
        listener = self._manager.global_listener
        if listener is not None:
            listener(self._stream, s)
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
        self._swallow: ContextVar[bool] = ContextVar(
            "sut_output_swallow", default=True
        )
        self._sinks: ContextVar[tuple[_OutputSink, ...]] = ContextVar(
            "sut_output_sinks", default=()
        )
        self._original_stdout: TextIO | None = None
        self._original_stderr: TextIO | None = None
        self._depth: int = 0
        self._lock: RLock = RLock()
        self._global_listener: _OutputSink | None = None

    def set_global_listener(self, listener: _OutputSink) -> None:
        self._global_listener = listener

    def clear_global_listener(self) -> None:
        self._global_listener = None

    @property
    def global_listener(self) -> _OutputSink | None:
        return self._global_listener

    @property
    def is_installed(self) -> bool:
        return self._depth > 0

    @contextmanager
    def sys_capture(self, *, swallow: bool) -> Iterator[None]:
        with self.installed():
            token = self._swallow.set(swallow)
            try:
                yield
            finally:
                self._swallow.reset(token)

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
                    self._swallow,
                    self,
                    is_stdout=True,
                )
                sys.stderr = _SysStreamDispatcher(
                    original_stderr,
                    self._sinks,
                    self._swallow,
                    self,
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
    def __init__(self) -> None:
        self._execution_id: ContextVar[UUID | None] = ContextVar(
            f"sut_{id(self)}_output_execution_id",
            default=None,
        )
        self._events: ContextVar[list[CapturedEvent] | None] = ContextVar(
            f"sut_{id(self)}_output_events",
            default=None,
        )

    @property
    def output(self) -> CapturedOutput:
        return CapturedOutput.from_events(self._events_list())

    @property
    def stdout(self) -> CapturedStream:
        return self.output.stdout

    @property
    def stderr(self) -> CapturedStream:
        return self.output.stderr

    def clear(self) -> None:
        self._events_list().clear()

    def reset(self, execution_id: UUID | None) -> None:
        if (
            self._execution_id.get() == execution_id
            and self._events.get() is not None
        ):
            return
        self._execution_id.set(execution_id)
        self._events.set([])

    def wrap(
        self,
        original_callable: Callable[..., object],
        *,
        is_async: bool,
    ) -> Callable[..., object]:
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
        with _sys_capture.installed(), _sys_capture.sink(self._append):
            yield

    @classmethod
    def is_sys_capture_installed(cls) -> bool:
        return _sys_capture.is_installed

    @classmethod
    @contextmanager
    def sys_capture(cls, *, swallow: bool) -> Iterator[None]:
        with _sys_capture.sys_capture(swallow=swallow):
            yield

    @classmethod
    def set_global_listener(cls, listener: _OutputSink) -> None:
        _sys_capture.set_global_listener(listener)

    @classmethod
    def clear_global_listener(cls) -> None:
        _sys_capture.clear_global_listener()

    def _append(self, stream: OutputStream, text: str) -> None:
        self._events_list().append(CapturedEvent(stream, text))

    def _events_list(self) -> list[CapturedEvent]:
        events = self._events.get()
        if events is None:
            events = []
            self._events.set(events)
        return events
