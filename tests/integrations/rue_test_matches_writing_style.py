import rue
from rue import Case
from rue.predicates import matches_writing_style

from pydantic import BaseModel, Field


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must match
        the writing style of the reference document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases,
        the actual document must match the writing
        style of this document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — stricter style matching.
        Not strict mode — more permissive style
        matching.
        """,
    )


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual document matches the
        writing style of the reference document.
        False means the actual document does not
        match the writing style of the reference
        document.
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
async def test_matches_writing_style_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_writing_style(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_writing_style_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_writing_style(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_writing_style_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_writing_style(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_writing_style_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_writing_style(**case.input_kwargs)
