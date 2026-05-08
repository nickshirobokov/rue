"""Execution backend models."""

from __future__ import annotations

from enum import StrEnum


class ExecutionBackend(StrEnum):
    """Where a test node suites."""

    MAIN = "main"
    MODULE_MAIN = "module_main"
    ASYNCIO = "asyncio"
    SUBPROCESS = "subprocess"
