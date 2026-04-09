"""Test modifiers - pure data classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rue.testing.models.case import Case, CaseGroup


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
    display_name: str = "iterate"


@dataclass(frozen=True)
class ParamsIterateModifier:
    """Run the inner execution for each parameter set."""

    parameter_sets: tuple[ParameterSet, ...]
    min_passes: int
    display_name: str = "params"


@dataclass(frozen=True)
class CasesIterateModifier:
    """Run the inner execution for each case."""

    cases: tuple[Case[Any, Any], ...]
    min_passes: int
    display_name: str = "cases"


@dataclass(frozen=True)
class GroupsIterateModifier:
    """Run the inner execution for each case group."""

    groups: tuple[CaseGroup[Any, Any, Any], ...]
    min_passes: int
    display_name: str = "groups"


Modifier = (
    IterateModifier
    | ParamsIterateModifier
    | CasesIterateModifier
    | GroupsIterateModifier
)
