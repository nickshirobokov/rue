"""Test modifiers - pure data classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rue.testing.models.case import Case, CaseGroup


if TYPE_CHECKING:
    from rue.testing.execution.backend import ExecutionBackend


@dataclass(frozen=True)
class ParameterSet:
    """Concrete parameter combination for an individual test run."""

    values: dict[str, Any]
    suffix: str


@dataclass(frozen=True)
class IterateModifier:
    """Run the inner execution N times."""

    count: int
    min_passes: int
    display_name: str = "iterations"

    @property
    def display_summary(self) -> str:
        return f"x {self.count} {self.display_name}"


@dataclass(frozen=True)
class ParamsIterateModifier:
    """Run the inner execution for each parameter set."""

    parameter_sets: tuple[ParameterSet, ...]
    min_passes: int
    display_name: str = "parameter sets"

    @property
    def display_summary(self) -> str:
        return f"x {len(self.parameter_sets)} {self.display_name}"


@dataclass(frozen=True)
class CasesIterateModifier:
    """Run the inner execution for each case."""

    cases: tuple[Case[Any, Any], ...]
    min_passes: int
    display_name: str = "cases"

    @property
    def display_summary(self) -> str:
        return f"x {len(self.cases)} {self.display_name}"


@dataclass(frozen=True)
class GroupsIterateModifier:
    """Run the inner execution for each case group."""

    groups: tuple[CaseGroup[Any, Any, Any], ...]
    min_passes: int
    display_name: str = "groups"

    @property
    def display_summary(self) -> str:
        return f"x {len(self.groups)} {self.display_name}"


@dataclass(frozen=True)
class BackendModifier:
    """Select the execution backend for the test subtree."""

    backend: ExecutionBackend
    display_name: str = "backend changed"

    @property
    def display_summary(self) -> str:
        return ""


Modifier = (
    IterateModifier
    | ParamsIterateModifier
    | CasesIterateModifier
    | GroupsIterateModifier
    | BackendModifier
)
