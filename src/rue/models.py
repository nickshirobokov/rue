"""Shared serializable spec primitives."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Locator:
    """Serializable location of a Rue-defined callable."""

    module_path: Path | None
    function_name: str
    class_name: str | None = None

    def __str__(self) -> str:
        """Return a compact human-readable locator."""
        module_name = (
            "<dynamic>"
            if self.module_path is None
            else self.module_path.stem
        )
        if self.class_name:
            return f"{module_name}::{self.class_name}::{self.function_name}"
        return f"{module_name}::{self.function_name}"


@dataclass(slots=True)
class Spec(ABC):
    """Base model for objects that consume or provide Rue resources."""

    locator: Locator
