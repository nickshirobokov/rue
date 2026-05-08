"""Test modifiers - pure data classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rue.testing.models.case import Case, CaseFactory, CaseGroup


if TYPE_CHECKING:
    from rue.testing.execution.backend import ExecutionBackend


@dataclass(frozen=True)
class ParameterSet:
    """Concrete parameter combination for an individual test execution."""

    values: dict[str, Any]
    suffix: str


@dataclass(frozen=True)
class IterateModifier:
    """Execute the inner test N times."""

    count: int
    min_passes: int
    display_name: str = "iterations"

    @property
    def display_summary(self) -> str:
        """Short label shown next to iterated test names."""
        return f"x {self.count} {self.display_name}"


@dataclass(frozen=True)
class ParamsIterateModifier:
    """Execute the inner test once for each parameter set."""

    parameter_sets: tuple[ParameterSet, ...]
    min_passes: int
    display_name: str = "parameter sets"

    @property
    def display_summary(self) -> str:
        """Short label shown next to iterated test names."""
        return f"x {len(self.parameter_sets)} {self.display_name}"


@dataclass(frozen=True)
class CasesIterateModifier:
    """Execute the inner test once for each case."""

    cases: tuple[Case[Any, Any] | CaseFactory, ...]
    min_passes: int
    display_name: str = "cases"

    @property
    def display_summary(self) -> str:
        """Short label shown next to iterated test names."""
        return f"x {len(self.cases)} {self.display_name}"


@dataclass(frozen=True)
class GroupsIterateModifier:
    """Execute the inner test once for each case group."""

    groups: tuple[CaseGroup[Any, Any, Any], ...]
    min_passes: int
    display_name: str = "groups"

    @property
    def display_summary(self) -> str:
        """Short label shown next to iterated test names."""
        return f"x {len(self.groups)} {self.display_name}"


@dataclass(frozen=True)
class BackendModifier:
    """Select the execution backend for the test subtree."""

    backend: ExecutionBackend
    display_name: str = "backend changed"

    @property
    def display_summary(self) -> str:
        """Short label shown next to iterated test names."""
        return ""


Modifier = (
    IterateModifier
    | ParamsIterateModifier
    | CasesIterateModifier
    | GroupsIterateModifier
    | BackendModifier
)
