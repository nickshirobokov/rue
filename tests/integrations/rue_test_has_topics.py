import rue
from rue import Case
from rue.predicates import has_topics

from pydantic import BaseModel, Field


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must cover
        all topics from the reference document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases,
        all topics from this document must be covered
        by the actual document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — stricter topic matching.
        Not strict mode — more permissive topic
        matching.
        """,
    )


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual document covers all
        topics from the reference document. False
        means at least one topic from the reference
        document is missing from the actual document.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = []


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topics_strict_false_expected_true(case: Case[Inputs, Refs]):
    assert await has_topics(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topics_strict_false_expected_false(case: Case[Inputs, Refs]):
    assert not await has_topics(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topics_strict_true_expected_true(case: Case[Inputs, Refs]):
    assert await has_topics(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topics_strict_true_expected_false(case: Case[Inputs, Refs]):
    assert not await has_topics(**case.input_kwargs)
