"""Processor that persists OpenTelemetry traces to the local Rue directory."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from rue.events import RunEventsProcessor
from rue.telemetry.otel.backend import OtelTraceArtifact


if TYPE_CHECKING:
    from rue.config import Config
    from rue.testing import LoadedTestDef
    from rue.testing.models.executed import ExecutedTest
    from rue.testing.models.run import Run


DEFAULT_OTEL_OUTPUT_ROOT = Path(".rue/traces")
MAX_STORED_OTEL_RUNS = 5
UUID_STRING_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class OtelReporter(RunEventsProcessor):
    """Stores OpenTelemetry trace payloads under `.rue/traces`."""

    def __init__(self) -> None:
        self._prepared_run_ids: set[UUID] = set()

    def configure(self, config: Config) -> None:
        """Accept runtime configuration."""
        _ = config

    async def on_no_tests_found(self, run: Run) -> None:
        """Ignore empty runs."""
        _ = run
        return None

    async def on_collection_complete(
        self, items: list[LoadedTestDef], run: Run
    ) -> None:
        """Reset per-run trace directory tracking."""
        _ = items, run
        self._prepared_run_ids.clear()
        return None

    async def on_execution_complete(
        self, execution: ExecutedTest, run: Run
    ) -> None:
        """Persist the execution OpenTelemetry trace artifact."""
        _ = run
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
        if artifact.execution_id != execution.execution_id:
            raise ValueError("OTEL artifact execution_id does not match")

        run_dir = self._prepare_run_directory(artifact.run_id)
        trace_path = run_dir / f"{execution.execution_id}.json"
        trace_path.write_text(
            json.dumps(self._serialize_trace_artifact(artifact), indent=2),
            encoding="utf-8",
        )
        return None

    async def on_run_complete(self, run: Run) -> None:
        """Prune old run trace directories."""
        _ = run
        self._prune_run_directories()
        return None

    async def on_run_stopped_early(
        self, failure_count: int, run: Run
    ) -> None:
        """Ignore early-stop notifications."""
        _ = failure_count, run
        return None

    def _serialize_trace_artifact(
        self, artifact: OtelTraceArtifact
    ) -> dict[str, Any]:
        return {
            "run_id": str(artifact.run_id),
            "execution_id": str(artifact.execution_id),
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

    def _prepare_run_directory(self, run_id: UUID) -> Path:
        DEFAULT_OTEL_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        run_dir = DEFAULT_OTEL_OUTPUT_ROOT / str(run_id)
        if run_id not in self._prepared_run_ids:
            if run_dir.exists():
                shutil.rmtree(run_dir)
            run_dir.mkdir(parents=True, exist_ok=True)
            self._prepared_run_ids.add(run_id)
        elif not run_dir.exists():
            run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _prune_run_directories(self) -> None:
        run_dirs = sorted(
            [
                path
                for path in DEFAULT_OTEL_OUTPUT_ROOT.iterdir()
                if path.is_dir() and UUID_STRING_PATTERN.fullmatch(path.name)
            ],
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for run_dir in run_dirs[MAX_STORED_OTEL_RUNS:]:
            shutil.rmtree(run_dir)


otel_reporter = OtelReporter()
