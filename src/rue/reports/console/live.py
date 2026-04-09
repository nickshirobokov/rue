"""Manages the Rich Live display lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console, RenderableType
from rich.live import Live

if TYPE_CHECKING:
    pass


class LiveDisplay:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._live: Live | None = None

    @property
    def active(self) -> bool:
        return self._live is not None

    def start(self, initial: RenderableType) -> None:
        self._live = Live(
            initial,
            console=self._console,
            auto_refresh=True,
            refresh_per_second=1,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._live.start()

    def refresh(self, renderable: RenderableType) -> None:
        if self._live is not None:
            self._live.update(renderable, refresh=True)

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
