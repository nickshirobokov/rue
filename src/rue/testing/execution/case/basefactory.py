"""Base class for generated case factories."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from rue.testing.execution.case.models import Case


if TYPE_CHECKING:
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


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
