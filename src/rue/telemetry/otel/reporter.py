"""Processor that persists OpenTelemetry traces to the local Rue directory."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from rue.events import SuiteEventsProcessor
from rue.telemetry.otel.models import OtelTraceArtifact


if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing.execution.suite.models import ExecutedSuite
    from rue.testing.execution.test.models import ExecutedTest, LoadedTestDef


DEFAULT_OTEL_OUTPUT_ROOT = Path(".rue/traces")
MAX_STORED_OTEL_SUITES = 5
UUID_STRING_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class OtelReporter(SuiteEventsProcessor):
    """Stores OpenTelemetry trace payloads under `.rue/traces`."""

    def __init__(self) -> None:
        self._prepared_suite_execution_ids: set[UUID] = set()

    def configure(self, config: Config) -> None:
        """Accept runtime configuration."""
        _ = config

    async def on_no_tests_found(self, suite: ExecutedSuite) -> None:
        """Ignore empty suites."""
        _ = suite
        return None

    async def on_collection_complete(
        self, items: list[LoadedTestDef], suite: ExecutedSuite
    ) -> None:
        """Reset per-suite trace directory tracking."""
        _ = items, suite
        self._prepared_suite_execution_ids.clear()
        return None

    async def on_test_execution_complete(
        self, execution: ExecutedTest, suite: ExecutedSuite
    ) -> None:
        """Persist the test execution OpenTelemetry trace artifact."""
        _ = suite
        artifacts = [
            artifact
            for artifact in execution.telemetry_artifacts
            if isinstance(artifact, OtelTraceArtifact)
        ]
        if not artifacts:
            return None
        if len(artifacts) != 1:
            raise ValueError("Expected exactly one OTEL trace artifact")

        artifact = artifacts[0]
        if artifact.test_execution_id != execution.test_execution_id:
            raise ValueError("OTEL artifact test_execution_id does not match")

        suite_dir = self._prepare_suite_directory(
            artifact.suite_execution_id
        )
        trace_path = suite_dir / f"{execution.test_execution_id}.json"
        trace_path.write_text(
            json.dumps(self._serialize_trace_artifact(artifact), indent=2),
            encoding="utf-8",
        )
        return None

    async def on_suite_execution_complete(self, suite: ExecutedSuite) -> None:
        """Prune old suite trace directories."""
        _ = suite
        self._prune_suite_directories()
        return None

    async def on_suite_stopped_early(
        self,
        failure_count: int,
        suite: ExecutedSuite,
    ) -> None:
        """Ignore early-stop notifications."""
        _ = failure_count, suite
        return None

    def _serialize_trace_artifact(
        self, artifact: OtelTraceArtifact
    ) -> dict[str, Any]:
        return {
            "suite_execution_id": str(artifact.suite_execution_id),
            "test_execution_id": str(artifact.test_execution_id),
            "trace": self._build_trace_tree(artifact.spans),
        }

    def _build_trace_tree(self, spans: list[dict[str, Any]]) -> dict[str, Any]:
        nodes_by_span_id = {
            span["context"]["span_id"]: {**span, "children": []}
            for span in spans
        }
        roots: list[dict[str, Any]] = []

        for span in spans:
            node = nodes_by_span_id[span["context"]["span_id"]]
            parent_id = span["parent_id"]
            if parent_id is None:
                roots.append(node)
                continue
            nodes_by_span_id[parent_id]["children"].append(node)

        return roots[0]

    def _prepare_suite_directory(self, suite_execution_id: UUID) -> Path:
        DEFAULT_OTEL_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        suite_dir = DEFAULT_OTEL_OUTPUT_ROOT / str(suite_execution_id)
        if suite_execution_id not in self._prepared_suite_execution_ids:
            if suite_dir.exists():
                shutil.rmtree(suite_dir)
            suite_dir.mkdir(parents=True, exist_ok=True)
            self._prepared_suite_execution_ids.add(suite_execution_id)
        elif not suite_dir.exists():
            suite_dir.mkdir(parents=True, exist_ok=True)
        return suite_dir

    def _prune_suite_directories(self) -> None:
        suite_dirs = sorted(
            [
                path
                for path in DEFAULT_OTEL_OUTPUT_ROOT.iterdir()
                if path.is_dir() and UUID_STRING_PATTERN.fullmatch(path.name)
            ],
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for suite_dir in suite_dirs[MAX_STORED_OTEL_SUITES:]:
            shutil.rmtree(suite_dir)
