"""Reporter that persists OpenTelemetry traces to the local Rue directory."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from rue.reports.base import Reporter

if TYPE_CHECKING:
    from rue.testing import TestDefinition
    from rue.testing.models.result import TestExecution
    from rue.testing.models.run import Run
    from rue.testing.tracing import TestTracer


DEFAULT_OTEL_OUTPUT_ROOT = Path(".rue/traces")
MAX_STORED_OTEL_RUNS = 5
UUID_STRING_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class OtelReporter(Reporter):
    """Stores OpenTelemetry trace payloads under `.rue/traces`."""

    def __init__(self) -> None:
        self._prepared_run_ids: set[UUID] = set()

    async def on_no_tests_found(self) -> None:
        return None

    async def on_collection_complete(self, items: list[TestDefinition]) -> None:
        _ = items
        self._prepared_run_ids.clear()
        return None

    async def on_test_complete(self, execution: TestExecution) -> None:
        _ = execution
        return None

    async def on_run_complete(self, run: Run) -> None:
        _ = run
        self._prune_run_directories()
        return None

    async def on_run_stopped_early(self, failure_count: int) -> None:
        _ = failure_count
        return None

    async def on_trace_collected(
        self, tracer: TestTracer, execution_id: UUID
    ) -> None:
        session = tracer.completed_otel_trace_session
        if session is None:
            return None

        run_dir = self._prepare_run_directory(session.run_id)
        trace_path = run_dir / f"{execution_id}.json"
        trace_path.write_text(
            json.dumps(session.serialize(), separators=(",", ":")),
            encoding="utf-8",
        )
        return None

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
