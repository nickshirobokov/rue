import rue
from rue import Case
from rue.predicates import has_conflicting_facts

from pydantic import BaseModel, Field


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must contain at least one fact that
        conflicts with a fact from the reference
        document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases,
        this document must contain at least one fact
        that conflicts with a fact from the actual
        document.
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
        True means at least one fact in the actual
        document conflicts with at least one fact in
        the reference document. False means the two
        documents contain no conflicting facts.
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
async def test_has_conflicting_facts_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await has_conflicting_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_conflicting_facts_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await has_conflicting_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_conflicting_facts_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await has_conflicting_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_conflicting_facts_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await has_conflicting_facts(**case.input_kwargs)
