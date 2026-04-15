"""Test definition model — process-bound pair of spec + live callable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rue.testing.models.spec import TestSpec


@dataclass
class TestDefinition:
    """A discovered test function ready for execution in the current process.

    Pairs a serializable :class:`TestSpec` with the live callable resolved
    by the loader.  The ``spec`` is the cross-process-safe record; ``fn`` is
    the process-local binding.

    ``fail_fast`` is the one runtime-mutable field: it is not part of the
    spec because it is set by the :class:`Runner` after collection, not by
    user decorators.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    spec: TestSpec
    fn: Callable[..., Any]
    fail_fast: bool = field(default=False)
