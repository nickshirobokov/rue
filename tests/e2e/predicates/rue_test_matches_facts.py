# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import matches_facts

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


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

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual and reference
        documents are factually equivalent. False
        means the two documents are not factually
        equivalent.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:certificate_rotation_equivalent_very_easy",
        ),
        metadata={
            "slug": "certificate_rotation_equivalent_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Change ticket CHG-8471

        Customer: Harbor Path Dental
        Service: api.harborpath.example
        Window: Saturday, May 4, 2025, 22:00-23:30 PT
        Change owner: Mira Salgado
        Reason: replace the TLS certificate before the current chain expires
        Rehearsal finding: mobile-app logins failed while ingress still served the
        old certificate
        Execution: installed renewed certificate, recycled ingress pods, reran login
        smoke tests
        Outcome: login access restored before window close and no data loss
        """,
            reference="""
        Mira Salgado scheduled a certificate rotation for
        api.harborpath.example on behalf of Harbor Path Dental for Saturday, May 4,
        2025 from 10:00 to 11:30 p.m. Pacific. The reason was to replace the TLS
        certificate before expiration. During rehearsal, mobile users could not log
        in while ingress continued serving the old certificate. In the approved
        window, the team installed the renewed certificate, restarted the ingress
        pods, reran login checks, restored access before close, and confirmed that
        no customer data was lost.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:redis_migration_equivalent_easy"),
        metadata={
            "slug": "redis_migration_equivalent_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        {
          "client": "Northwind Clinics",
          "owner": "Priya Nair",
          "change": "migrate Redis session storage to cluster-b",
          "window_start": "2025-06-18T23:00:00-07:00",
          "window_end": "2025-06-19T00:30:00-07:00",
          "expected_impact": "brief logout for users with active browser sessions",
          "rollback": "point applications back to cluster-a"
        }
        """,
            reference="""
        Priya Nair is running a change for Northwind Clinics to migrate Redis-backed
        session storage onto cluster-b. The maintenance window starts at 11:00 p.m.
        Pacific on June 18, 2025 and ends at 12:30 a.m. on June 19. The team expects
        a brief logout for users who already have browser sessions open, and the
        rollback plan is to point the applications back to cluster-a.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:redis_migration_equivalent_medium"
        ),
        metadata={
            "slug": "redis_migration_equivalent_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        change: migrate Redis session storage to cluster-b
        client: Northwind Clinics
        owner: Priya Nair
        window_start: 2025-06-18 23:00 PT
        window_end: 2025-06-19 00:30 PT
        expected_impact: brief logout for users with active browser sessions
        rollback: point applications back to cluster-a
        """,
            reference="""
        Priya Nair is running a change for Northwind Clinics to migrate Redis-backed
        session storage onto cluster-b. The maintenance window starts at 11:00 p.m.
        Pacific on June 18, 2025 and ends at 12:30 a.m. on June 19. The team expects
        a brief logout for users who already have browser sessions open, and the
        rollback plan is to point the applications back to cluster-a.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:civic_listing_superset_not_equivalent_very_easy",
        ),
        metadata={
            "slug": "civic_listing_superset_not_equivalent_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Marketplace post for a used car:

        Selling my 2018 Honda Civic EX in silver. The car has 82,140 miles, a clean
        title, and one previous owner. I replaced the front brake pads in January,
        installed a new battery in March, and I still have both original key fobs.
        Registration is paid through November. The only cosmetic issue is a scrape on
        the rear bumper from a parking garage pillar.
        """,
            reference="""
        Selling a 2018 Honda Civic EX with 82,140 miles, a clean title, and one
        previous owner.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:self_introduction_not_equivalent_easy"
        ),
        metadata={
            "slug": "self_introduction_not_equivalent_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Onboarding recap from the support manager:

        During Monday's orientation, the new support hire introduced himself as
        Roger Hale, said he had moved over from the Phoenix office three weeks ago,
        and mentioned that he would spend his first two shifts shadowing the returns
        queue before taking live chats on his own.
        """,
            reference="""
        The new support hire's name is Roger Hale.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:self_introduction_not_equivalent_medium"
        ),
        metadata={
            "slug": "self_introduction_not_equivalent_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Orientation transcript excerpt:

        Roger Hale introduced himself during Monday's orientation, said he had
        transferred from the Phoenix office three weeks earlier, and noted that
        his first two shifts would be on the returns queue. He also said he had
        already completed the knowledge-base certification over the weekend.
        """,
            reference="""
        Orientation transcript excerpt:

        Roger Hale introduced himself during Monday's orientation, said he had
        transferred from the Phoenix office three weeks earlier, and noted that
        his first two shifts would be on the returns queue. He also said he still
        needed to complete the knowledge-base certification this week.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:migration_celebration_equivalent_open_world_very_easy",
        ),
        metadata={
            "slug": "migration_celebration_equivalent_open_world_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Channel follow-up after the cutover:

        Yesterday, once the warehouse migration finally settled down, the team spent
        the rest of the evening together downtown and actually enjoyed themselves for
        the first time all week. People were laughing again and the night felt like a
        real celebration instead of another extension of the incident call.
        """,
            reference="""
        Thanks for dinner downtown after yesterday's warehouse migration. The team
        had a great time together and finally looked relaxed again.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:titan_losses_equivalent_open_world_easy"
        ),
        metadata={
            "slug": "titan_losses_equivalent_open_world_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Prepared remarks from the quarterly review:

        In Q3 we posted roughly a billion dollars in losses tied to the Titan phone
        recovery program. Leadership said the biggest driver was the camera module
        failure in the early production run, plus a handful of smaller hardware
        defects that pushed return rates up and forced extra service credits. Finance
        added that the pressure was concentrated in the premium model rather than the
        budget line.
        """,
            reference="""
        Poor returns on the Titan premium phone were driven by camera problems and
        speaker defects, and the issue hit the company hard financially.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:titan_losses_equivalent_open_world_medium",
        ),
        metadata={
            "slug": "titan_losses_equivalent_open_world_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Quarterly review transcript:

        Return rates on the Titan premium handset spiked after early camera
        failures and a speaker defect surfaced in the same recovery cycle. What
        had looked like a product-quality issue turned into a serious financial
        drag on the company before the quarter closed.
        """,
            reference="""
        Poor returns on the Titan premium phone were driven by camera problems and
        speaker defects, and the issue hit the company hard financially.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:migration_celebration_not_equivalent_closed_world_very_easy",
        ),
        metadata={
            "slug": "migration_celebration_not_equivalent_closed_world_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Channel follow-up after the cutover:

        Yesterday, once the warehouse migration finally settled down, the team spent
        the rest of the evening together downtown and actually enjoyed themselves for
        the first time all week.
        """,
            reference="""
        Thanks for dinner downtown after yesterday's warehouse migration. The team
        had a great time together and finally looked relaxed again.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:titan_losses_not_equivalent_closed_world_easy",
        ),
        metadata={
            "slug": "titan_losses_not_equivalent_closed_world_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Earnings briefing summary:

        The company said the Titan recovery program produced roughly a billion
        dollars in losses. Executives blamed the early camera defect and several
        smaller hardware issues that inflated return rates and warranty credits,
        especially in the premium model. They did not break out every smaller defect
        on the call.
        """,
            reference="""
        Speaker defects and camera failures in the Titan premium model drove poor
        returns, leading the company to lose $1 billion.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:titan_losses_not_equivalent_closed_world_medium",
        ),
        metadata={
            "slug": "titan_losses_not_equivalent_closed_world_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Earnings prep draft:

        The Titan recovery program produced about a billion dollars in losses,
        mostly in the premium model. Executives singled out the early camera
        failure, then collapsed the rest into several secondary hardware issues
        that raised returns and warranty credits.

        The briefing notes stayed at that grouped level and did not identify the
        remaining defects individually.
        """,
            reference="""
        Speaker defects and camera failures in the Titan premium model drove poor
        returns, leading the company to lose $1 billion.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
]


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and not case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_facts_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_facts(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_facts_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_facts(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_facts_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_facts(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_facts_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_facts(**case.inputs.model_dump())
