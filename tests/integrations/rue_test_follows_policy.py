import rue
from rue import Case
from rue.predicates import follows_policy

from pydantic import BaseModel, Field


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual text. For positive cases, this text
        must follow the policy described in the
        reference text.
        """,
    )
    reference: str = Field(
        description="""
        The reference policy. For positive cases, the
        actual text must comply with this policy.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — stricter policy compliance.
        Not strict mode — more permissive policy
        compliance.
        """,
    )


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual text follows the policy
        described in the reference text. False means
        the actual text violates the policy described
        in the reference text.
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
async def test_follows_policy_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await follows_policy(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_follows_policy_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await follows_policy(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_follows_policy_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await follows_policy(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_follows_policy_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await follows_policy(**case.input_kwargs)
