"""Execution base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rue.resources.resolver import ResourceResolver
from rue.testing.models.result import TestExecution


class Test(ABC):
    """Executable test - single or composite."""

    @abstractmethod
    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute the test and return result."""
