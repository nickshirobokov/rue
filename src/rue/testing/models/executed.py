"""Executed test records."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from rue.telemetry.base import TelemetryArtifact
from rue.testing.models.loaded import LoadedTestDef
from rue.testing.models.result import TestResult, TestStatus


@dataclass
class ExecutedTest:
    """Complete record of a test execution, combining context and result.

    Encapsulates both the test context (inputs/setup) and the result (outcome)
    as a single execution record.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    definition: LoadedTestDef
    result: TestResult
    execution_id: UUID
    telemetry_artifacts: tuple[TelemetryArtifact, ...] = ()
    sub_executions: list[ExecutedTest] = field(default_factory=list)

    @property
    def status(self) -> TestStatus:
        """Convenience access to result status."""
        return self.result.status

    @property
    def duration_ms(self) -> float:
        """Convenience access to result duration."""
        return self.result.duration_ms

    @property
    def label(self) -> str:
        dlabel = self.definition.spec.get_label()
        if dlabel:
            return dlabel
        if self.execution_id:
            return str(self.execution_id)[:8]
        return "case"
