"""Execution base classes."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from rue.context.runtime import CURRENT_RUNNER
from rue.resources.resolver import ResourceResolver
from rue.testing.models.definition import TestDefinition
from rue.testing.models.result import TestExecution, TestResult, TestStatus


class Test(ABC):
    """Executable test - single or composite."""

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
