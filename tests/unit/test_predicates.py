import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from rue.context import predicate_results_collector
from rue.predicates import PredicateResult, predicate
from rue.predicates.clients import LLMPredicate, WithExplanationOutput
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
def returns_result(
    actual: str,
    reference: str,
    *,
    strict: bool = False,
    confidence: float = 0.6,
    message: str | None = "from-result",
) -> PredicateResult:
    return PredicateResult(
        actual=actual,
        reference=reference,
        name="returns_result",
        strict=strict,
        confidence=confidence,
        value=actual == reference,
        message=message,
    )


class FakeProcessor:
    def __init__(self, value: bool | WithExplanationOutput) -> None:
        self.value = value

    async def process(
        self,
        _content: object,
        run_context: object,
    ) -> bool | WithExplanationOutput:
        _ = run_context
        return self.value


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
    clear_traces()
    yield output_path
    clear_traces()


def _span_from_output(trace_output_path: Path, name: str) -> dict[str, Any]:
    for line in trace_output_path.read_text().splitlines():
        span = json.loads(line)
        if span["name"] == name:
            return span
    raise AssertionError(f"Missing span {name!r}")


def test_decorated_predicate_returns_bool_and_records_metadata():
    assert equals("a", "a") is True

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
    assert results[0].actual == "a"
    assert results[0].reference == "b"
    assert results[0].name == "equals"
    assert results[0].strict is False
    assert results[0].confidence == 0.25
    assert results[0].value is False
    assert results[0].message == "nope"


def test_decorated_predicate_uses_declared_defaults_for_bool_metadata():
    @predicate
    def with_defaults(
        actual: str,
        reference: str,
        *,
        strict: bool = False,
        confidence: float = 0.4,
        message: str | None = "defaulted",
    ) -> bool:
        return actual == reference

    results: list[PredicateResult] = []

    with predicate_results_collector(results):
        verdict = with_defaults("A", "a")

    assert verdict is False
    assert len(results) == 1
    assert results[0].actual == "A"
    assert results[0].reference == "a"
    assert results[0].name == "with_defaults"
    assert results[0].strict is False
    assert results[0].confidence == 0.4
    assert results[0].message == "defaulted"


def test_decorated_predicate_uses_declared_defaults_for_result_metadata():
    results: list[PredicateResult] = []

    with predicate_results_collector(results):
        verdict = returns_result("A", "a")

    assert verdict is False
    assert len(results) == 1
    assert results[0].actual == "A"
    assert results[0].reference == "a"
    assert results[0].name == "returns_result"
    assert results[0].strict is False
    assert results[0].confidence == 0.6
    assert results[0].message == "from-result"


def test_decorated_predicate_passes_through_predicate_result():
    results: list[PredicateResult] = []

    with predicate_results_collector(results):
        verdict = returns_result(
            "same",
            "same",
            strict=True,
            confidence=0.25,
            message="kept",
        )

    assert verdict is True
    assert len(results) == 1
    assert results[0].actual == "same"
    assert results[0].reference == "same"
    assert results[0].name == "returns_result"
    assert results[0].strict is True
    assert results[0].confidence == 0.25
    assert results[0].message == "kept"


def test_decorated_predicate_rejects_missing_actual_reference_params():
    with pytest.raises(
        TypeError,
        match="must declare 'actual' and 'reference' as named positional parameters",
    ):

        @predicate
        def invalid(left: str, right: str) -> bool:
            return left == right


def test_decorated_predicate_rejects_positional_only_actual_reference_params():
    with pytest.raises(
        TypeError,
        match="must declare 'actual' and 'reference' as named positional parameters",
    ):

        @predicate
        def invalid(actual: str, reference: str, /) -> bool:
            return actual == reference


def test_decorated_predicate_rejects_keyword_only_actual_reference_params():
    with pytest.raises(
        TypeError,
        match="must declare 'actual' and 'reference' as named positional parameters",
    ):

        @predicate
        def invalid(*, actual: str, reference: str) -> bool:
            return actual == reference


def test_decorated_predicate_creates_sync_trace_span(trace_output_path: Path):
    assert equals(
        "abc",
        "a",
        strict=False,
        confidence=0.25,
        message="prefix",
    ) is False

    span = _span_from_output(trace_output_path, "predicate.equals")
    attrs = span["attributes"]

    assert attrs.get("rue.predicate") is True
    assert attrs.get("rue.predicate.name") == "equals"
    assert attrs.get("predicate.value") is False
    assert attrs.get("predicate.strict") is False
    assert attrs.get("predicate.confidence") == 0.25
    assert attrs.get("predicate.input.actual") == "'abc'"
    assert attrs.get("predicate.input.reference") == "'a'"
    assert attrs.get("predicate.message") == "'prefix'"


@pytest.mark.asyncio
async def test_decorated_predicate_creates_async_trace_span(
    trace_output_path: Path,
):
    assert await async_equals(
        "abc",
        "ABC",
        strict=False,
        confidence=0.75,
    ) is True

    span = _span_from_output(trace_output_path, "predicate.async_equals")
    attrs = span["attributes"]

    assert attrs.get("rue.predicate") is True
    assert attrs.get("rue.predicate.name") == "async_equals"
    assert attrs.get("predicate.value") is True
    assert attrs.get("predicate.strict") is False
    assert attrs.get("predicate.confidence") == 0.75
    assert attrs.get("predicate.input.actual") == "'abc'"
    assert attrs.get("predicate.input.reference") == "'ABC'"


def test_predicate_trace_content_can_be_disabled(
    trace_output_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("RUE_TRACE_CONTENT", "false")

    assert equals(
        "a",
        "b",
        strict=False,
        confidence=0.25,
        message="nope",
    ) is False

    span = _span_from_output(trace_output_path, "predicate.equals")
    attrs = span["attributes"]

    assert attrs.get("rue.predicate") is True
    assert attrs.get("rue.predicate.name") == "equals"
    assert attrs.get("predicate.value") is False
    assert attrs.get("predicate.strict") is False
    assert attrs.get("predicate.confidence") == 0.25
    assert "predicate.input.actual" not in attrs
    assert "predicate.input.reference" not in attrs
    assert "predicate.message" not in attrs


@pytest.mark.asyncio
async def test_llm_predicate_returns_bool_and_records_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    predicate_client = LLMPredicate(
        predicate_name="has_demo",
        normal_prompt="normal",
        strict_prompt="strict",
        task_template="{actual} :: {reference}",
    )

    async def fake_model_request(**_kwargs) -> SimpleNamespace:
        return SimpleNamespace(parts=[SimpleNamespace(content="ignored")])

    monkeypatch.setattr(
        predicate_client,
        "get_model_config",
        lambda: ("demo:model", object()),
    )
    monkeypatch.setattr(
        predicate_client,
        "bool_with_explanation_output_schema",
        SimpleNamespace(
            text_processor=FakeProcessor(
                WithExplanationOutput(
                    explanation="predicate failed",
                    verdict=False,
                )
            )
        ),
    )
    monkeypatch.setattr(
        predicate_client,
        "bool_with_explanation_request_parameters",
        object(),
    )
    monkeypatch.setattr(
        "rue.predicates.clients.infer_model",
        lambda _model: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "rue.predicates.clients.model_request",
        fake_model_request,
    )

    results: list[PredicateResult] = []
    with predicate_results_collector(results):
        verdict = await predicate_client(
            "actual text",
            "reference text",
            strict=True,
            with_explanation=True,
        )

    assert verdict is False
    assert len(results) == 1
    assert results[0].actual == "actual text"
    assert results[0].reference == "reference text"
    assert results[0].name == "has_demo"
    assert results[0].strict is True
    assert results[0].confidence == 1.0
    assert results[0].value is False
    assert results[0].message == "predicate failed"

    assert (
        await predicate_client(
            "actual text",
            "reference text",
            strict=True,
            with_explanation=True,
        )
        is False
    )
    assert len(results) == 1
