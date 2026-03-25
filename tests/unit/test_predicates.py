import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from rue.context import predicate_results_collector
from rue.predicates import PredicateResult, predicate
from rue.testing.discovery import collect
from rue.testing.runner import Runner
from rue.tracing import clear_traces, set_trace_output_path


@predicate
def equals(
    actual: str,
    reference: str,
    *,
    strict: bool = True,
    confidence: float = 1.0,
    message: str | None = None,
) -> bool:
    _ = confidence, message
    if strict:
        return actual == reference
    return actual.casefold() == reference.casefold()


@predicate
async def async_returns_result(
    actual: str,
    reference: str,
    *,
    strict: bool = False,
    confidence: float = 0.6,
    message: str | None = "ignored",
) -> PredicateResult:
    _ = strict, confidence, message
    return PredicateResult(
        actual=f"{actual}!",
        reference=f"{reference}?",
        name="async_result_payload",
        strict=True,
        confidence=0.6,
        value=actual == reference,
        message="from-result",
    )


@predicate
async def async_equals(
    actual: str,
    reference: str,
    *,
    strict: bool = True,
    confidence: float = 1.0,
    message: str | None = None,
) -> bool:
    _ = confidence, message
    if strict:
        return actual == reference
    return actual.casefold() == reference.casefold()


@pytest.fixture
def trace_output_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("RUE_TRACE_CONTENT", raising=False)
    output_path = tmp_path / "predicate_traces.jsonl"
    set_trace_output_path(output_path)
    return output_path


@pytest.fixture(autouse=True)
def clear_traces_each(trace_output_path: Path) -> None:
    clear_traces()
    yield
    clear_traces()


def _span_from_output(trace_output_path: Path, name: str) -> dict[str, object]:
    for line in trace_output_path.read_text().splitlines():
        span = json.loads(line)
        if span["name"] == name:
            return span
    raise AssertionError(f"Missing span {name!r}")


def _trace_names(trace_output_path: Path) -> set[str]:
    return {
        json.loads(line)["name"]
        for line in trace_output_path.read_text().splitlines()
        if line
    }


def _write_temp_module(tmp_path: Path, source: str) -> tuple[str, Path]:
    mod_name = f"rue_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(source.lstrip())
    return mod_name, mod_path


def test_sync_predicate_collects_normalized_result():
    results: list[PredicateResult] = []

    with predicate_results_collector(results):
        verdict = equals(
            "a",
            "b",
            strict=False,
            confidence=0.25,
            message="nope",
        )

    assert verdict is False
    assert len(results) == 1
    assert results[0].model_dump() == {
        "actual": "a",
        "reference": "b",
        "name": "equals",
        "strict": False,
        "confidence": 0.25,
        "value": False,
        "message": "nope",
    }


@pytest.mark.asyncio
async def test_async_predicate_collects_returned_result_without_normalizing():
    results: list[PredicateResult] = []

    with predicate_results_collector(results):
        verdict = await async_returns_result(
            "left",
            "right",
            strict=False,
            confidence=0.1,
            message="ignored",
        )

    assert verdict is False
    assert len(results) == 1
    assert results[0].model_dump() == {
        "actual": "left!",
        "reference": "right?",
        "name": "async_result_payload",
        "strict": True,
        "confidence": 0.6,
        "value": False,
        "message": "from-result",
    }


def test_sync_predicate_writes_trace_attributes(trace_output_path: Path):
    assert equals(
        "abc",
        "a",
        strict=False,
        confidence=0.25,
        message="prefix",
    ) is False

    span = _span_from_output(trace_output_path, "predicate.equals")
    attrs = span["attributes"]

    assert attrs["rue.predicate"] is True
    assert attrs["rue.predicate.name"] == "equals"
    assert attrs["predicate.value"] is False
    assert attrs["predicate.strict"] is False
    assert attrs["predicate.confidence"] == 0.25
    assert attrs["predicate.input.actual"] == "'abc'"
    assert attrs["predicate.input.reference"] == "'a'"
    assert attrs["predicate.message"] == "'prefix'"


@pytest.mark.asyncio
async def test_async_predicate_writes_trace_attributes(trace_output_path: Path):
    assert await async_equals(
        "abc",
        "ABC",
        strict=False,
        confidence=0.75,
    ) is True

    span = _span_from_output(trace_output_path, "predicate.async_equals")
    attrs = span["attributes"]

    assert attrs["rue.predicate"] is True
    assert attrs["rue.predicate.name"] == "async_equals"
    assert attrs["predicate.value"] is True
    assert attrs["predicate.strict"] is False
    assert attrs["predicate.confidence"] == 0.75
    assert attrs["predicate.input.actual"] == "'abc'"
    assert attrs["predicate.input.reference"] == "'ABC'"
    assert "predicate.message" not in attrs


def test_predicate_rejects_missing_reference_parameter():
    with pytest.raises(
        TypeError,
        match="must declare named 'actual' and 'reference' parameters",
    ):

        @predicate
        def invalid(actual: str) -> bool:
            return True


def test_predicate_rejects_positional_only_actual_reference_parameters():
    with pytest.raises(
        TypeError,
        match="must declare named 'actual' and 'reference' parameters",
    ):

        @predicate
        def invalid(actual: str, reference: str, /) -> bool:
            return actual == reference


def test_predicate_accepts_keyword_only_actual_reference_parameters():
    @predicate
    def keyword_only(*, actual: str, reference: str) -> bool:
        return actual == reference

    assert keyword_only(actual="a", reference="a") is True


def test_predicate_uses_signature_binding_for_missing_call_arguments():
    with pytest.raises(TypeError, match="reference"):
        equals("a")


@pytest.mark.asyncio
async def test_runner_collects_predicate_results_and_trace_data_into_db(
    tmp_path: Path,
    null_reporter,
):
    mod_name, mod_path = _write_temp_module(
        tmp_path,
        """
from rue.predicates import predicate

@predicate
def equals(
    actual: str,
    reference: str,
    *,
    strict: bool = False,
    confidence: float = 0.25,
    message: str | None = "db-message",
) -> bool:
    return actual == reference

def test_sample():
    assert equals("a", "b"), "predicate failed"
""",
    )
    db_path = tmp_path / "rue.db"
    trace_path = tmp_path / "runner_traces.jsonl"

    try:
        items = collect(mod_path)
        set_trace_output_path(trace_path)

        run = await Runner(
            reporters=[null_reporter],
            enable_tracing=True,
            trace_output=trace_path,
            db_enabled=True,
            db_path=db_path,
        ).run(items=items)

        execution = run.result.executions[0]
        assert execution.status.value == "failed"
        assert len(execution.result.assertion_results) == 1
        assert len(execution.result.assertion_results[0].predicate_results) == 1

        predicate_result = execution.result.assertion_results[0].predicate_results[0]
        assert predicate_result.model_dump() == {
            "actual": "a",
            "reference": "b",
            "name": "equals",
            "strict": False,
            "confidence": 0.25,
            "value": False,
            "message": "db-message",
        }

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            assertion = conn.execute(
                "SELECT * FROM assertions WHERE test_execution_id = ?",
                (str(execution.execution_id),),
            ).fetchone()
            assert assertion is not None

            predicate_rows = conn.execute(
                "SELECT * FROM predicates WHERE assertion_id = ?",
                (assertion["id"],),
            ).fetchall()
            trace_rows = conn.execute(
                "SELECT name FROM trace_spans WHERE test_execution_id = ?",
                (str(execution.execution_id),),
            ).fetchall()

        assert len(predicate_rows) == 1
        predicate_row = dict(predicate_rows[0])
        assert predicate_row["predicate_name"] == "equals"
        assert predicate_row["actual"] == "a"
        assert predicate_row["reference"] == "b"
        assert predicate_row["strict"] == 0
        assert predicate_row["confidence"] == 0.25
        assert predicate_row["value"] == 0
        assert predicate_row["message"] == "db-message"

        trace_names = {row["name"] for row in trace_rows}
        assert "predicate.equals" in trace_names
        assert f"test.{mod_name}::test_sample" in trace_names
        assert "predicate.equals" in _trace_names(trace_path)
    finally:
        sys.modules.pop(mod_name, None)
