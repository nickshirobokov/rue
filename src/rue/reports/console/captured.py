"""Captures stderr during a run and renders it as a WARNINGS section."""

from __future__ import annotations

import sys
from collections import Counter
from typing import IO

from rich.console import RenderableType
from rich.rule import Rule
from rich.text import Text


class StderrCapture:
    def __init__(self) -> None:
        self._lines: list[str] = []
        self._buf: str = ""
        self._original: IO[str] | None = None

    def start(self) -> None:
        self._lines.clear()
        self._buf = ""
        self._original = sys.stderr
        sys.stderr = self  # type: ignore[assignment]

    def stop(self) -> None:
        if self._original is None:
            return
        sys.stderr = self._original
        self._original = None
        if self._buf.strip():
            self._lines.append(self._buf.rstrip())
            self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._lines.append(line)
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    @property
    def lines(self) -> list[str]:
        return list(self._lines)


class CapturedOutputRenderer:
    def render(self, lines: list[str]) -> list[RenderableType]:
        if not lines:
            return []
        renderables: list[RenderableType] = [Text(""), Rule("WARNINGS", characters="=")]
        for line, count in Counter(lines).items():
            label = f"{line} (x{count})" if count > 1 else line
            renderables.append(Text(label, style="yellow dim"))
        renderables.append(Text(""))
        return renderables
