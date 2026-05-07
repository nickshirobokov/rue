"""Shared serializable spec primitives."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Locator:
    """Serializable location of a Rue-defined module member.

    Dynamic callables are unsupported; Rue locators always carry a source file.
    """

    module_path: Path
    function_name: str
    class_name: str | None = None

    def __str__(self) -> str:
        """Return a compact human-readable locator."""
        module_name = self.module_path.stem
        if self.class_name:
            return f"{module_name}::{self.class_name}::{self.function_name}"
        return f"{module_name}::{self.function_name}"


@dataclass(slots=True)
class Spec(ABC):
    """Base model for objects that consume or provide Rue resources."""

    locator: Locator

    @property
    def name(self) -> str:
        """Return the callable name represented by this spec."""
        return self.locator.function_name
