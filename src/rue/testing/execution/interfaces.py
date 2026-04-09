"""Execution base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from rue.resources.resolver import ResourceResolver
from rue.testing.models.definition import TestDefinition
from rue.testing.models.result import TestExecution


class Test(ABC):
    """Executable test - single or iterated."""

    @abstractmethod
    async def execute(self, resolver: ResourceResolver) -> TestExecution:
        """Execute the test and return result."""


class TestFactory(ABC):
    """Creates Test instances from definitions."""

    @abstractmethod
    def build(
        self,
        definition: TestDefinition,
        params: dict[str, Any] | None = None,
    ) -> Test:
        """Build appropriate executable test from definition."""
