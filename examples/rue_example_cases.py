"""Examples for `Case` and `iter_cases`."""

from __future__ import annotations

from pydantic import BaseModel

import rue
from rue import Case


# =============================== Define SUT ===============================


def simple_chatbot(prompt: str) -> str:
    if "verbose" in prompt:
        answer = "What an excellent question! The answer is: "
    else:
        answer = ""
    if "France" in prompt:
        return answer + "Paris"
    if "Germany" in prompt:
        return answer + "Berlin"
    if "rock" in prompt:
        return answer + "Metallica"
    if "pop" in prompt:
        return answer + "Lady Gaga"
    raise ValueError(f"Unknown query: {prompt}")


# =============================== Prepare test cases ===============================


# Models for references are optional but helpful for static type checking
class ExampleReferences(BaseModel):
    expected: str
    max_len: int
    min_len: int


class ExampleInputs(BaseModel):
    prompt: str


# Define all cases
all_cases = [
    Case[ExampleInputs, ExampleReferences](
        tags={"geography"},
        metadata={"verbose": False},
        references=ExampleReferences(expected="Paris", max_len=10, min_len=1),
        inputs=ExampleInputs(
            prompt="What is the capital of France? Be concise."
        ),
    ),
    Case[ExampleInputs, ExampleReferences](
        tags={"geography"},
        metadata={"verbose": True},
        references=ExampleReferences(
            expected="Berlin", max_len=10000, min_len=20
        ),
        inputs=ExampleInputs(
            prompt="What is the capital of Germany? Be verbose."
        ),
    ),
    Case[ExampleInputs, ExampleReferences](
        tags={"music"},
        metadata={"verbose": True},
        references=ExampleReferences(
            expected="Metallica", max_len=10000, min_len=20
        ),
        inputs=ExampleInputs(prompt="What is the best rock band? Be verbose."),
    ),
    Case[ExampleInputs, ExampleReferences](
        tags={"music"},
        metadata={"verbose": False},
        references=ExampleReferences(
            expected="Lady Gaga", max_len=10, min_len=1
        ),
        inputs=ExampleInputs(prompt="What is the best pop band? Be concise."),
    ),
]


# =============================== Run tests ===============================


# Get output for each case input and assert against references
@rue.iter_cases(*all_cases)
def test_iter_cases_basic_usage(case: Case[ExampleInputs, ExampleReferences]):
    response = simple_chatbot(**case.inputs.model_dump())

    assert case.references.expected in response
    assert len(response) <= case.references.max_len
    assert len(response) >= case.references.min_len


# Filter cases in code
@rue.iter_cases(*[c for c in all_cases if "geography" in c.tags])
def test_iter_cases_only_geography(
    case: Case[ExampleInputs, ExampleReferences],
):
    response = simple_chatbot(**case.inputs.model_dump())

    assert case.references.expected in response
    assert len(response) <= case.references.max_len
    assert len(response) >= case.references.min_len


# Fail early if any case has invalid input
@rue.resource.sut(validate_cases=all_cases)
def chatbot():
    return simple_chatbot


@rue.iter_cases(*all_cases)
def test_iter_cases_with_validation(
    case: Case[ExampleInputs, ExampleReferences], chatbot
):
    response = chatbot(**case.inputs.model_dump())

    assert case.references.expected in response
    assert len(response) <= case.references.max_len
    assert len(response) >= case.references.min_len
