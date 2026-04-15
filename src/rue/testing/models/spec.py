"""Serializable test specification — process-boundary-safe models.

These models carry all test metadata that can cross a process boundary
(no live callables). They are the wire format between the parent discovery
process and any worker that materializes and executes tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from rue.testing.models.modifiers import Modifier


@dataclass(frozen=True)
class TestLocator:
    """Uniquely identifies a test function. Fully serializable.

    Sufficient to find the function in any process that has access to the
    filesystem and can import the module via a TestLoader.
    """

    module_path: Path
    function_name: str
    class_name: str | None = None

    def __str__(self) -> str:
        if self.class_name:
            return f"{self.module_path.stem}::{self.class_name}::{self.function_name}"
        return f"{self.module_path.stem}::{self.function_name}"


@dataclass(frozen=True)
class TestSpec:
    """Fully serializable test specification produced during discovery.

    Contains every piece of metadata needed to understand and schedule a
    test, but holds no live Python objects (no callables, no module
    references). A worker process deserializes this and passes it to
    ``TestLoader.materialize()`` to obtain a runnable ``TestDefinition``.
    """

    locator: TestLocator
    is_async: bool
    params: tuple[str, ...]
    modifiers: tuple[Modifier, ...]
    tags: frozenset[str]
    skip_reason: str | None = None
    xfail_reason: str | None = None
    xfail_strict: bool = False
    definition_error: str | None = None
    inline: bool = False
    suffix: str | None = None
    case_id: UUID | None = None

    # --- Convenience properties mirroring TestDefinition's interface ---

    @property
    def name(self) -> str:
        return self.locator.function_name

    @property
    def module_path(self) -> Path:
        return self.locator.module_path

    @property
    def class_name(self) -> str | None:
        return self.locator.class_name

    @property
    def full_name(self) -> str:
        return str(self.locator)

    @property
    def label(self) -> str | None:
        if self.suffix:
            return self.suffix
        if self.case_id:
            return str(self.case_id)
        return None

    def with_changes(self, **kwargs) -> TestSpec:
        """Return a new TestSpec with selected fields replaced."""
        return replace(self, **kwargs)
