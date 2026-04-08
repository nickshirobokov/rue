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
class RepeatModifier:
    """Repeat the inner execution N times."""

    count: int
    min_passes: int
    display_name: str = "repeat"


@dataclass(frozen=True)
class ParametrizeModifier:
    """Run the inner execution for each parameter set."""

    parameter_sets: tuple[ParameterSet, ...]
    display_name: str = "parametrize"


@dataclass(frozen=True)
class CaseIterateModifier:
    """Run the inner execution for each case."""

    cases: tuple[Case[Any, Any], ...]
    min_passes: int
    display_name: str = "cases"


@dataclass(frozen=True)
class CaseGroupIterateModifier:
    """Run the inner execution for each case group."""

    groups: tuple[CaseGroup[Any, Any, Any], ...]
    display_name: str = "case groups"


Modifier = (
    RepeatModifier
    | ParametrizeModifier
    | CaseIterateModifier
    | CaseGroupIterateModifier
)
