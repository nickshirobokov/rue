"""Testing models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rue.context.models import RunEnvironment
from rue.context.runtime import RunContext
from rue.testing.models.case import Case, CaseFactory, CaseGroup
from rue.testing.models.spec import (
    Locator,
    SetupFileRef,
    TestSpec,
    TestSpecCollection,
)


_RUN_EXPORTS: frozenset[str] = frozenset({"ExecutedRun", "RunResult"})

_EXECUTION_NAMES: frozenset[str] = frozenset(
    {
        "ExecutedTest",
        "LoadedTestDef",
        "TestResult",
        "TestStatus",
    }
)

if TYPE_CHECKING:
    from rue.testing.execution.models import (
        ExecutedTest,
        LoadedTestDef,
        TestResult,
        TestStatus,
    )
    from rue.testing.models.run import ExecutedRun, RunResult


def __getattr__(name: str) -> Any:
    if name in _RUN_EXPORTS:
        from rue.testing.models import run as run_module  # noqa: PLC0415

        return getattr(run_module, name)
    # ``execution.models`` imports ``models.spec``; lazy load breaks the cycle.
    if name in _EXECUTION_NAMES:
        from rue.testing.execution import models as execution_models  # noqa: I001, PLC0415

        return getattr(execution_models, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    base = {*globals(), *_EXECUTION_NAMES, *_RUN_EXPORTS}
    return sorted(base)


__all__ = [
    "Case",
    "CaseFactory",
    "CaseGroup",
    "ExecutedRun",
    "ExecutedTest",
    "LoadedTestDef",
    "Locator",
    "RunContext",
    "RunEnvironment",
    "RunResult",
    "SetupFileRef",
    "TestResult",
    "TestSpec",
    "TestSpecCollection",
    "TestStatus",
]
