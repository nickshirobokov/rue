"""Execution-layer value types shared across local and remote paths."""

from __future__ import annotations

from enum import StrEnum


class ExecutionBackend(StrEnum):
    """Where a test node runs."""

    MAIN = "main"
    ASYNCIO = "asyncio"
    SUBPROCESS = "subprocess"
