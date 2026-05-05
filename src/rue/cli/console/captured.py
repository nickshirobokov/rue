"""Captures stderr during a run and renders it as a WARNINGS section."""

# ruff: noqa: D101,D102

from __future__ import annotations

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
