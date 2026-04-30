"""Rue tests for comparing chatbot experiment variants."""

from collections.abc import Callable, Iterator

import rue
from rue import SUT, Case, Metric, metrics

from .conftest import (
    FACTUAL_CASES,
    PROMPT_INSTRUCTION_CASES,
    SAFETY_CASES,
    ChatbotInputs,
    ChatbotReferences,
)


@rue.resource.metric(scope="run")
def factual_mistakes_rate() -> Iterator[Metric | float]:
    """Track mean factual mistakes per factual case."""
    metric = Metric()
    yield metric
    yield metric.mean


@rue.resource(scope="test")
def case_factual_mistakes(
    factual_mistakes_rate: Metric,
) -> Iterator[Metric]:
    """Track factual mistakes for one case and report them upward."""
    metric = Metric()
    yield metric

    mistakes = metric.counter[False]
    factual_mistakes_rate.add_record(mistakes)


@rue.resource.metric(scope="run")
def unsafe_behaviors_count() -> Iterator[Metric | int]:
    """Track total unsafe behavior checks that failed."""
    metric = Metric()
    yield metric
    yield int(metric.sum)


@rue.resource(scope="test")
def case_unsafe_behaviors(
    unsafe_behaviors_count: Metric,
) -> Iterator[Metric]:
    """Track unsafe behaviors for one case and report them upward."""
    metric = Metric()
    yield metric

    unsafe_behaviors = metric.counter[False]
    unsafe_behaviors_count.add_record(unsafe_behaviors)


@rue.resource.metric(scope="run")
def violated_prompt_instructions_count() -> Iterator[Metric | int]:
    """Track total prompt-instruction checks that failed."""
    metric = Metric()
    yield metric
    yield int(metric.sum)


@rue.resource(scope="test")
def case_violated_prompt_instructions(
    violated_prompt_instructions_count: Metric,
) -> Iterator[Metric]:
    """Track prompt-instruction violations for one case."""
    metric = Metric()
    yield metric

    violations = metric.counter[False]
    violated_prompt_instructions_count.add_record(violations)


@rue.test.iterate.cases(*FACTUAL_CASES)
def test_answers_do_not_make_factual_mistakes(
    case: Case[ChatbotInputs, ChatbotReferences],
    chatbot: SUT[Callable[..., str]],
    case_factual_mistakes: Metric,
) -> None:
    """Check support answers against factual reference data."""
    response = chatbot.instance(**case.inputs.model_dump())

    with metrics(case_factual_mistakes):
        for term in case.references.required_terms:
            assert term in response
        for term in case.references.forbidden_terms:
            assert term not in response


@rue.test.iterate.cases(*SAFETY_CASES, min_passes=2)
def test_unsafe_requests_are_refused(
    case: Case[ChatbotInputs, ChatbotReferences],
    chatbot: SUT[Callable[..., str]],
    case_unsafe_behaviors: Metric,
) -> None:
    """Check that unsafe requests do not produce unsafe behavior."""
    response = chatbot.instance(**case.inputs.model_dump())

    with metrics(case_unsafe_behaviors):
        for term in case.references.required_terms:
            assert term in response
        for term in case.references.forbidden_terms:
            assert term not in response


@rue.test.iterate.cases(*PROMPT_INSTRUCTION_CASES, min_passes=5)
def test_prompt_instructions_are_followed(
    case: Case[ChatbotInputs, ChatbotReferences],
    chatbot: SUT[Callable[..., str]],
    case_violated_prompt_instructions: Metric,
) -> None:
    """Check explicit answer-shape and routing instructions."""
    response = chatbot.instance(**case.inputs.model_dump())

    with metrics(case_violated_prompt_instructions):
        for term in case.references.required_terms:
            assert term in response
        for term in case.references.forbidden_terms:
            assert term not in response
        assert len(response.split()) <= case.references.max_words
