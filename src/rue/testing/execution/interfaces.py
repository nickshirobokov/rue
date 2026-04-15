"""Execution base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from rue.resources.resolver import ResourceResolver
from rue.testing.models.result import TestExecution

if TYPE_CHECKING:
    from rue.testing.models.loaded import LoadedTestDef


class ExecutableTest(ABC):
    """Executable test - single or composite."""

    definition: LoadedTestDef

    @abstractmethod
    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute the test and return result."""
