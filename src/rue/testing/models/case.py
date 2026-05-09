"""Test case definitions and decorators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypeVar


if TYPE_CHECKING:
    from rue.testing.execution.models import ExecutedTest, LoadedTestDef


InputsT = TypeVar("InputsT", default=dict[str, Any])
RefsT = TypeVar("RefsT", default=dict[str, Any])
GroupRefsT = TypeVar("GroupRefsT", default=dict[str, Any])


# Data model for case values


class Case(BaseModel, Generic[InputsT, RefsT]):
    """Container for a single test case inputs and references.

    Attributes:
    ----------
    id : UUID
        Unique identifier for the test case, defaults to a new UUID.
    tags : set[str]
        Set of tags for filtering or categorization of the test case.
    metadata : dict[str, str | int | float | bool | None]
        Arbitrary key-value pairs for additional context or reporting.
    inputs : InputsT
        Input arguments to be passed to the System Under Test (SUT).
    references : RefsT,
        Reference data used for validation or comparison during testing.
    """

    model_config = ConfigDict(validate_default=True, frozen=True)

    id: UUID = Field(default_factory=uuid4)
    tags: set[str] = Field(default_factory=set)
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict
    )
    inputs: InputsT = Field(default_factory=dict)  # type: ignore[assignment]
    references: RefsT = Field(default_factory=dict)  # type: ignore[assignment]


class CaseFactory(ABC):
    """Stateful engine that emits generated cases during test execution."""

    max_attempts: int
    display_name: str

    def __init__(
        self,
        *,
        max_attempts: int,
        display_name: str = "factory",
    ) -> None:
        if max_attempts < 1:
            msg = (
                "CaseFactory max_attempts must be >= 1, "
                f"got {max_attempts}"
            )
            raise ValueError(msg)
        self.max_attempts = max_attempts
        self.display_name = display_name

    @abstractmethod
    async def next_case(
        self,
        loaded_test: LoadedTestDef,
    ) -> Case[Any, Any] | None:
        """Return the next generated case or ``None`` when exhausted."""
        raise NotImplementedError

    async def observe(
        self,
        case: Case[Any, Any],
        execution: ExecutedTest,
    ) -> None:
        """Receive the result for a generated case."""
        _ = case, execution


class CaseGroup(BaseModel, Generic[InputsT, RefsT, GroupRefsT]):
    """Named collection of related cases with a group-level pass threshold.

    A ``CaseGroup`` bundles several :class:`Case` instances that logically
    belong together (e.g. the same feature, the same edge-case family) and
    lets you set how many of them must pass for the whole group to be
    considered passing via ``min_passes``.

    Use with ``@rue.test.iterate.groups(...)`` to iterate a test function
    over multiple groups; each group is executed as a nested case-iterated
    test execution.

    Attributes:
    ----------
    name : str
        Human-readable label that identifies the group in reports and
        test execution trees.
    cases : list[Case[InputsT, RefsT]]
        Ordered list of cases belonging to the group. Must contain at
        least one case.
    references : GroupRefsT
        Group-level reference data shared across all cases in the group,
        useful for assertions that depend on group context rather than
        individual case references.
    min_passes : int
        Minimum number of cases that must pass for the group to be
        considered passing. Defaults to ``1``; cannot exceed ``len(cases)``.
    """

    model_config = ConfigDict(validate_default=True, frozen=True)

    name: str
    cases: list[Case[InputsT, RefsT]] = Field(
        default_factory=list, min_length=1
    )
    references: GroupRefsT = Field(default_factory=dict)  # type: ignore[assignment]
    min_passes: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_min_passes(self) -> CaseGroup[InputsT, RefsT, GroupRefsT]:
        """Ensure the group threshold can be reached by its cases."""
        if self.min_passes > len(self.cases):
            msg = (
                f"min_passes ({self.min_passes}) cannot exceed cases count "
                f"({len(self.cases)})"
            )
            raise ValueError(msg)
        return self
