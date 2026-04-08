import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from rue.config import RueConfig
from rue.context.collectors import CURRENT_PREDICATE_RESULTS
from rue.context.runtime import bind
from rue.predicates import PredicateResult, predicate
from rue.testing.discovery import collect
from rue.testing.runner import Runner


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


def _write_temp_module(tmp_path: Path, source: str) -> tuple[str, Path]:
    mod_name = f"rue_{uuid4().hex}"
    mod_path = tmp_path / f"{mod_name}.py"
    mod_path.write_text(source.lstrip())
    return mod_name, mod_path


async def _run_module_with_tracing(
    *,
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    db_enabled: bool = False,
    db_path: Path | None = None,
):
    mod_name, mod_path = _write_temp_module(tmp_path, source)

    try:
        monkeypatch.chdir(tmp_path)
        items = collect(mod_path)
        runner = Runner(
            config=RueConfig.model_construct(
                otel=True,
                db_enabled=db_enabled,
                db_path=db_path,
            ),
            reporters=[trace_reporter],
        )
        run = await runner.run(items=items)
        return mod_name, run, trace_reporter.sessions
    finally:
        sys.modules.pop(mod_name, None)


def test_sync_predicate_collects_normalized_result():
    results: list[PredicateResult] = []

    with bind(CURRENT_PREDICATE_RESULTS, results):
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

    with bind(CURRENT_PREDICATE_RESULTS, results):
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "span_name", "expected_attrs"),
    [
        (
            """
from rue.predicates import predicate

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

def test_sample():
    assert equals(
        "abc",
        "a",
        strict=False,
        confidence=0.25,
        message="prefix",
    ) is False
""",
            "predicate.equals",
            {
                "rue.predicate": True,
                "rue.predicate.name": "equals",
                "predicate.value": False,
                "predicate.strict": False,
                "predicate.confidence": 0.25,
                "predicate.input.actual": "'abc'",
                "predicate.input.reference": "'a'",
                "predicate.message": "'prefix'",
            },
        ),
    ],
)
async def test_predicate_writes_trace_attributes(
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    span_name: str,
    expected_attrs: dict[str, object],
):
    mod_name, run, sessions = await _run_module_with_tracing(
        tmp_path=tmp_path,
        trace_reporter=trace_reporter,
        monkeypatch=monkeypatch,
        source=source,
    )

    assert run.result.passed == 1
    payloads = [session.serialize() for session in sessions]
    attrs = next(
        span["attributes"]
        for payload in payloads
        for span in payload["spans"]
        if span["name"] == span_name
    )

    for key, value in expected_attrs.items():
        assert attrs[key] == value
    if "predicate.message" not in expected_attrs:
        assert "predicate.message" not in attrs

    assert f"test.{mod_name}::test_sample" in {
        span["name"] for payload in payloads for span in payload["spans"]
    }


def test_predicate_rejects_missing_reference_parameter():
    with pytest.raises(
        TypeError,
        match="must declare named 'actual' and 'reference' parameters",
    ):

        @predicate
        def invalid(actual: str) -> bool:
            return True


def test_predicate_accepts_keyword_only_actual_reference_parameters():
    @predicate
    def keyword_only(*, actual: str, reference: str) -> bool:
        return actual == reference

    assert keyword_only(actual="a", reference="a") is True


@pytest.mark.asyncio
async def test_runner_collects_predicate_results_and_trace_data_into_db(
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "rue.db"
    mod_name, run, sessions = await _run_module_with_tracing(
        tmp_path=tmp_path,
        trace_reporter=trace_reporter,
        monkeypatch=monkeypatch,
        db_enabled=True,
        db_path=db_path,
        source="""
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

    execution = run.result.executions[0]
    assert execution.status.value == "failed"
    assert len(execution.result.assertion_results) == 1
    assert len(execution.result.assertion_results[0].predicate_results) == 1

    predicate_result = execution.result.assertion_results[0].predicate_results[
        0
    ]
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

    assert len(predicate_rows) == 1
    predicate_row = dict(predicate_rows[0])
    assert predicate_row["predicate_name"] == "equals"
    assert predicate_row["actual"] == "a"
    assert predicate_row["reference"] == "b"
    assert predicate_row["strict"] == 0
    assert predicate_row["confidence"] == 0.25
    assert predicate_row["value"] == 0
    assert predicate_row["message"] == "db-message"

    span_names = {
        span["name"]
        for payload in [session.serialize() for session in sessions]
        for span in payload["spans"]
    }
    assert "predicate.equals" in span_names
    assert f"test.{mod_name}::test_sample" in span_names


@pytest.mark.asyncio
async def test_predicate_does_not_trace_outside_runner_even_after_runtime_configured(
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
):
    _, _, sessions = await _run_module_with_tracing(
        tmp_path=tmp_path,
        trace_reporter=trace_reporter,
        monkeypatch=monkeypatch,
        source="""
def test_sample():
    assert True
""",
    )

    before = [session.serialize() for session in sessions]
    assert equals("abc", "ABC", strict=False) is True
    after = [session.serialize() for session in sessions]

    assert before == after


@pytest.mark.asyncio
async def test_predicate_trace_always_records_content_attributes(
    tmp_path: Path,
    trace_reporter,
    monkeypatch: pytest.MonkeyPatch,
):
    _, run, sessions = await _run_module_with_tracing(
        tmp_path=tmp_path,
        trace_reporter=trace_reporter,
        monkeypatch=monkeypatch,
        source="""
from rue.predicates import predicate

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
    return actual == reference

def test_sample():
    assert equals("abc", "xyz", strict=False, confidence=0.25, message="secret") is False
""",
    )

    assert run.result.passed == 1
    attrs = next(
        span["attributes"]
        for session in sessions
        for span in session.serialize()["spans"]
        if span["name"] == "predicate.equals"
    )

    assert attrs["rue.predicate"] is True
    assert attrs["predicate.value"] is False
    assert attrs["predicate.strict"] is False
    assert attrs["predicate.confidence"] == 0.25
    assert attrs["predicate.input.actual"] == "'abc'"
    assert attrs["predicate.input.reference"] == "'xyz'"
    assert attrs["predicate.message"] == "'secret'"
