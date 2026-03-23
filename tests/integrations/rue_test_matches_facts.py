import rue
from rue import Case
from rue.predicates import matches_facts

from pydantic import BaseModel, Field


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must be
        factually equivalent to the reference document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases,
        this document must be
        factually equivalent to the actual document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — closed-world assumption.
        Not strict mode — open-world
        assumption.
        """,
    )


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual and reference
        documents are factually equivalent. False
        means the two documents are not factually
        equivalent.
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
async def test_matches_facts_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_facts_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_facts_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_facts_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_facts(**case.input_kwargs)
