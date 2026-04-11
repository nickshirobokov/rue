"""Captures stderr during a run and renders it as a WARNINGS section."""

from __future__ import annotations

from collections import Counter

from rich.console import RenderableType
from rich.rule import Rule
from rich.text import Text

from rue.resources.sut.output import SUTOutputCapture


class StderrCapture:
    def __init__(self) -> None:
        self._lines: list[str] = []
        self._buf: str = ""

    def start(self) -> None:
        self._lines.clear()
        self._buf = ""
        SUTOutputCapture.set_global_listener(self._on_write)

    def stop(self) -> None:
        SUTOutputCapture.clear_global_listener()
        if self._buf.strip():
            self._lines.append(self._buf.rstrip())
            self._buf = ""

    def _on_write(self, stream: str, s: str) -> None:
        if stream != "stderr":
            return
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._lines.append(line)

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
