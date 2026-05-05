"""SUT output capture models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


type OutputStream = Literal["stdout", "stderr"]


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
