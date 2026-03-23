# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import has_unsupported_facts

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must contain at least one fact that
        is not supported by the reference document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases,
        this document must fail to support at least
        one fact from the actual document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — closed-world assumption.
        Not strict mode — open-world
        assumption.
        """,
    )

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual document contains at
        least one fact not supported by the reference
        document. False means every fact in the
        actual document is supported by the
        reference document.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:civic_listing_extra_details_very_easy"
        ),
        metadata={
            "slug": "civic_listing_extra_details_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Marketplace post for a used car:

        Selling my 2018 Honda Civic EX in silver. The car has 82,140 miles, a clean
        title, and one previous owner. I replaced the front brake pads in January,
        installed a new battery in March, and I still have both original key fobs.
        Registration is paid through November. The only cosmetic issue is a scrape on
        the rear bumper from a parking garage pillar. I am asking $13,400 and can
        meet near the Lake Merritt BART station on weeknights.
        """,
            reference="""
        Selling a 2018 Honda Civic EX with 82,140 miles, a clean title, and one
        previous owner.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:orientation_note_extra_events_easy"
        ),
        metadata={
            "slug": "orientation_note_extra_events_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Onboarding recap from the support manager:

        During Monday's orientation, the new support hire introduced himself as
        Roger Hale, said he had moved over from the Phoenix office three weeks ago,
        and mentioned that he would spend his first two shifts shadowing the returns
        queue before taking live chats on his own. He also told the room that he had
        already finished the knowledge-base certification over the weekend.
        """,
            reference="""
        The new support hire's name is Roger Hale. He will be working on the returns
        queue.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:lease_summary_supported_very_easy"
        ),
        metadata={
            "slug": "lease_summary_supported_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Lease transfer summary:

        Lena Ortiz will move into unit 4B at 214 Marigold Court on September 1,
        2025. The new rent is $2,450 per month and the lease includes one covered
        parking stall.
        """,
            reference="""
        Resident transfer summary for the 214 Marigold Court portfolio.

        Lena Ortiz asked to move from unit 2C to unit 4B after repeated late-night
        noise complaints from the upstairs tenant. The approved transfer date is
        September 1, 2025. The new lease rate for 4B is $2,450 per month, and the
        agreement includes one covered parking stall in the south garage. The
        existing $1,800 security deposit will carry over without a new inspection.
        Leasing approved one indoor cat on the file, but no dogs were authorized for
        this transfer. Key handoff is scheduled for 10:00 a.m. at the front office.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:migration_note_supported_in_open_world_easy",
        ),
        metadata={
            "slug": "migration_note_supported_in_open_world_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Note in the team channel:

        After yesterday's migration, everyone finally got to unwind together
        downtown and the mood was better than it had been all week. People were
        laughing again and the whole evening felt like a proper celebration instead
        of another incident bridge.
        """,
            reference="""
        Thanks for staying out after the migration last night. Dinner downtown ran
        long, everyone was laughing by the second round of appetizers, and it was
        the first time all week that the team looked relaxed.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:beacon_release_extra_feature_very_easy"
        ),
        metadata={
            "slug": "beacon_release_extra_feature_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Internal rollout note for Beacon 2.1:

        We shipped Beacon 2.1 on Tuesday at 09:15 UTC after a 15-minute read-only
        maintenance window. The release fixed the broken CSV export in the pipeline
        dashboard, moved audit logs into the new sidebar, and introduced Android
        parity for bulk approvals. Customer success was told to reassure accounts
        that saved filters stayed intact and no billing migration was part of this
        rollout.
        """,
            reference="""
        Beacon 2.1 shipped on Tuesday at 09:15 UTC after a 15-minute read-only
        window. The release fixed the broken CSV export and moved audit logs into
        the new sidebar.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:fundraising_precision_not_supported_easy",
        ),
        metadata={
            "slug": "fundraising_precision_not_supported_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Founder note to senior staff:

        River Lantern closed a $6.8 million extension financing on June 27, and
        North Ridge Capital was the sole lead. The plan is to use most of the money
        to hire 24 additional operations staff in Dallas while continuing the
        warehouse automation pilot through the end of the year. Leadership still
        describes the round as bridge financing ahead of a larger Series B process.
        """,
            reference="""
        Board update from River Lantern:

        The company closed a mid-seven-figure extension round late in Q2, and the
        memo describes the financing as a bridge from existing investors while the
        team lines up a larger Series B next spring. Management says most of the
        proceeds will go toward expanding the Dallas operations team and continuing
        the warehouse automation pilot.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:name_fact_supported_by_introduction_very_easy",
        ),
        metadata={
            "slug": "name_fact_supported_by_introduction_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Staffing update:

        The new support hire's name is Roger Hale, and he will start on the returns
        queue this week.
        """,
            reference="""
        Excerpt from the Monday orientation transcript:

        The new support hire introduced himself as Roger Hale, said he would spend
        his first two shifts shadowing the returns queue, and then thanked the room
        for helping him get his laptop working before the meeting.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:config_summary_supported_by_json_easy"
        ),
        metadata={
            "slug": "config_summary_supported_by_json_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Deployment summary for the Harbor Path API:

        The service is configured to retry failed requests three times, waits 250
        milliseconds between attempts, and sends alert emails to
        platform-alerts@harborpath.example.
        """,
            reference="""
        {
          "service": "harbor-path-api",
          "retries": {
            "max_attempts": 3,
            "backoff_ms": 250
          },
          "notifications": {
            "alert_email": "platform-alerts@harborpath.example",
            "pagerduty_service": "platform-core"
          },
          "owner": "api-infra"
        }
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
]


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_unsupported_facts_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await has_unsupported_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_unsupported_facts_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await has_unsupported_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_unsupported_facts_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await has_unsupported_facts(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_unsupported_facts_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await has_unsupported_facts(**case.input_kwargs)
