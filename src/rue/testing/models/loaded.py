"""Loaded test definition — process-bound pair of spec + live callable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rue.testing.models.spec import SetupFileRef, TestSpec


@dataclass
class LoadedTestDef:
    """A discovered test function ready for execution in the current process.

    Pairs a serializable :class:`TestSpec` with the live callable resolved
    by the loader.  The ``spec`` is the cross-process-safe record; ``fn`` is
    the process-local binding.

    ``fail_fast`` is the one runtime-mutable field: it is not part of the
    spec because it is set by the :class:`Runner` after collection, not by
    user decorators.

    ``suite_root`` and ``setup_chain`` capture the import context used to
    materialize this callable so expanded leaves still describe the original
    suite/session they came from.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    spec: TestSpec
    fn: Callable[..., Any]
    suite_root: Path = field(default_factory=Path)
    setup_chain: tuple[SetupFileRef, ...] = field(default_factory=tuple)
    fail_fast: bool = field(default=False)
