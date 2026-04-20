from uuid import UUID

import pytest
from pydantic import ValidationError

from rue.telemetry import OtelTraceArtifact


def test_otel_trace_artifact_forbids_extra_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OtelTraceArtifact(
            run_id=UUID(int=1),
            execution_id=UUID(int=2),
            trace_id="abc",
            spans=[],
            unexpected=True,
        )


def test_otel_trace_artifact_is_frozen():
    artifact = OtelTraceArtifact(
        run_id=UUID(int=1),
        execution_id=UUID(int=2),
        trace_id="abc",
        spans=[],
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        artifact.trace_id = "def"
