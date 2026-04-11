"""Test definition model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.testing.models.modifiers import Modifier


@dataclass
class TestDefinition:
    """A discovered test function or method."""

    __test__ = False  # Prevent pytest from collecting this as a test class

    name: str
    fn: Callable[..., Any]
    module_path: Path
    is_async: bool
    params: list[str] = field(default_factory=list)
    class_name: str | None = None
    modifiers: list[Modifier] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    skip_reason: str | None = None
    xfail_reason: str | None = None
    xfail_strict: bool = False
    definition_error: str | None = None
    inline: bool = False
    fail_fast: bool = False
    suffix: str | None = None
    case_id: UUID | None = None

    @property
    def full_name(self) -> str:
        """Full qualified name for display."""
        if self.class_name:
            return f"{self.module_path.stem}::{self.class_name}::{self.name}"
        return f"{self.module_path.stem}::{self.name}"

    @property
    def label(self) -> str | None:
        if self.suffix:
            return self.suffix
        if self.case_id:
            return str(self.case_id)
        return None
