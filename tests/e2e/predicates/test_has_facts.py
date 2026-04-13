# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import has_facts

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this document must contain
        all facts from the reference document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases, all facts from this document
        must be present in the actual document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — closed-world assumption. Not strict mode — open-world
        assumption.
        """,
    )

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual document contains all facts from the reference document.
        False means at least one fact described in the reference document is missing
        from the actual document.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:lease_transfer_very_easy"),
        metadata={
            "slug": "lease_transfer_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Resident transfer summary for the 214 Marigold Court portfolio.

        Lena Ortiz asked to move from unit 2C to unit 4B after repeated late-night
        noise complaints from the upstairs tenant. The approved transfer date is
        September 1, 2025. The new lease rate for 4B is $2,450 per month, and the
        agreement includes one covered parking stall in the south garage. The
        existing $1,800 security deposit will carry over without a new inspection.
        Leasing approved one indoor cat on the file, but no dogs were authorized for
        this transfer. Key handoff is scheduled for 10:00 a.m. at the front office.
        """,
            reference="""
        Lena Ortiz is transferring to unit 4B at 214 Marigold Court on September 1,
        2025. Her monthly rent for the new apartment is $2,450, and the lease
        includes one covered parking stall.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:certificate_rotation_easy"),
        metadata={"slug": "certificate_rotation_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        Change ticket CHG-8471

        Customer: Harbor Path Dental
        Service: api.harborpath.example
        Window: Saturday, May 4, 2025, 22:00-23:30 PT
        Change owner: Mira Salgado

        Reason for change:
        Replace the TLS certificate before the current chain expires on Monday
        morning.

        Rehearsal findings:
        During the dry run, mobile-app logins failed while the ingress layer kept
        serving the old certificate chain.

        Execution log:
        22:03 installed renewed certificate bundle
        22:11 recycled ingress pods in both production pools
        22:19 reran mobile and browser login smoke tests
        22:27 confirmed successful authentication

        Outcome:
        Login access was restored before the change window closed. No customer data
        loss occurred. Follow-up work is to add a 30-day certificate expiry alert.
        """,
            reference="""
        For Harbor Path Dental, Mira Salgado scheduled a certificate rotation for
        api.harborpath.example on Saturday, May 4, 2025 from 10:00 to 11:30 p.m.
        Pacific. The rehearsal showed that mobile users could not log in while the
        ingress layer still served the old certificate. During the window, the team
        installed the renewed certificate, restarted the ingress pods, and verified
        that login access was back before the change closed. No data was lost.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:certificate_rotation_medium"),
        metadata={
            "slug": "certificate_rotation_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Change ticket CHG-8471

        approved window: Saturday, May 4, 2025, 22:00-23:30 PT
        customer: Harbor Path Dental
        service: api.harborpath.example
        scheduled by: Mira Salgado

        Reason:
        api.harborpath.example needed the TLS chain replaced before the Monday
        morning expiry.

        Dry run:
        Mobile sign-ins kept failing whenever ingress continued presenting the old
        certificate chain. Browser checks recovered sooner, which is why the
        rehearsal notes singled out the mobile path.

        Cutover:
        22:03 renewed bundle loaded on the edge
        22:11 ingress pods recycled across both production pools
        22:19 login smoke tests rerun from mobile and browser flows
        22:27 auth checks green again

        Closeout:
        Access was back before 23:30 PT. No customer data was lost.
        """,
            reference="""
        For Harbor Path Dental, Mira Salgado scheduled a certificate rotation for
        api.harborpath.example on Saturday, May 4, 2025 from 10:00 to 11:30 p.m.
        Pacific. The rehearsal showed that mobile users could not log in while the
        ingress layer still served the old certificate. During the window, the team
        installed the renewed certificate, restarted the ingress pods, and verified
        that login access was back before the change closed. No data was lost.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:beacon_release_missing_feature_very_easy",
        ),
        metadata={
            "slug": "beacon_release_missing_feature_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Internal rollout note for Beacon 2.1:

        We shipped Beacon 2.1 on Tuesday at 09:15 UTC after a 15-minute read-only
        maintenance window. The release fixed the broken CSV export in the pipeline
        dashboard and moved audit logs into the new sidebar so support could stop
        sending customers to the legacy admin page. Customer success was told to
        reassure accounts that saved filters stayed intact and no billing migration
        was part of this rollout.
        """,
            reference="""
        Beacon 2.1 shipped on Tuesday at 09:15 UTC after a 15-minute read-only
        window. The release fixed the broken CSV export, moved audit logs into the
        new sidebar, and introduced Android parity for bulk approvals.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:bridge_round_too_vague_easy"),
        metadata={"slug": "bridge_round_too_vague_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        Board update from River Lantern:

        The company closed a mid-seven-figure extension round late in Q2, and the
        memo describes the financing as a bridge from existing investors while the
        team lines up a larger Series B next spring. Management says most of the
        proceeds will go toward expanding the Dallas operations team and continuing
        the warehouse automation pilot. The same note says churn improved during the
        quarter and that the extra cash should carry the business into next year.
        """,
            reference="""
        River Lantern closed a $6.8 million extension financing on June 27 that was
        led solely by North Ridge Capital. The company will use the proceeds
        primarily to hire 24 operations staff in Dallas and to continue the
        warehouse automation pilot.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:bridge_round_too_vague_medium"),
        metadata={
            "slug": "bridge_round_too_vague_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Board follow-up, messy notes:

        River Lantern closed a mid-seven-figure extension round right at the end of
        Q2. The money came from returning investors, with North Ridge
        participating again, and management keeps calling it bridge capital while
        they line up a bigger Series B for spring.

        Where funds go:
        mostly Dallas operations hiring, more work on the warehouse automation
        pilot, and enough buffer to get through next year if churn stays flat. The
        draft deck had several different hiring counts floating around, so the memo
        intentionally leaves the exact headcount out for now. Same with the final
        closing date; finance just says late June.
        """,
            reference="""
        River Lantern closed a $6.8 million extension financing on June 27 that was
        led solely by North Ridge Capital. The company will use the proceeds
        primarily to hire 24 operations staff in Dallas and to continue the
        warehouse automation pilot.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:migration_celebration_open_world_very_easy",
        ),
        metadata={
            "slug": "migration_celebration_open_world_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Slack note from Nina to the release channel:

        Yesterday evening, after we finally got the warehouse migration across the
        line, the whole crew stayed together downtown for a while. It was the first
        time all week that people were laughing instead of staring at rollback
        dashboards, and the mood completely flipped. By the time we headed home
        everyone was relaxed, full, and talking about something other than broken
        imports.
        """,
            reference="""
        After the warehouse migration yesterday, the team had dinner downtown and
        had a great time together.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:titan_losses_open_world_easy"),
        metadata={"slug": "titan_losses_open_world_easy", "difficulty": "easy"},
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
        id=uuid5(NAMESPACE_URL, f"{__name__}:titan_losses_open_world_medium"),
        metadata={
            "slug": "titan_losses_open_world_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Quarterly review transcript, cleaned up from notes:

        Most of the damage in the Titan recovery program sat in the premium phone
        line. Finance tied the return spike first to the early camera-module
        failure and then to a speaker defect that surfaced in the same production
        wave, with a few lesser hardware issues adding repair credits on top.

        By quarter-end the recovery program had turned into a major financial drag
        on the company.
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
            f"{__name__}:migration_celebration_closed_world_very_easy",
        ),
        metadata={
            "slug": "migration_celebration_closed_world_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Team note from the end of the cutover:

        Yesterday evening, once the migration drama was over, we all finally relaxed
        together downtown for a couple of hours. The mood was light again, people
        were telling stories from the cutover, and it felt like the first normal
        moment of the week.
        """,
            reference="""
        After the migration yesterday, the team had dinner downtown and had a great
        time together.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:titan_losses_closed_world_easy"),
        metadata={
            "slug": "titan_losses_closed_world_easy",
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
        id=uuid5(NAMESPACE_URL, f"{__name__}:titan_losses_closed_world_medium"),
        metadata={
            "slug": "titan_losses_closed_world_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Earnings prep draft:

        The Titan recovery program produced about a billion dollars in losses,
        concentrated in the premium model. Executives singled out the early camera
        module failure, then grouped the rest under several secondary hardware
        issues that pushed return rates and warranty credits higher.

        When analysts asked for a fuller parts breakdown, leadership stayed with
        the grouped summary and did not name the remaining defects individually.
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
async def test_has_facts_strict_false_expected_true(case: Case[Inputs, Refs]):
    assert await has_facts(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_has_facts_strict_false_expected_false(case: Case[Inputs, Refs]):
    assert not await has_facts(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_has_facts_strict_true_expected_true(case: Case[Inputs, Refs]):
    assert await has_facts(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_has_facts_strict_true_expected_false(case: Case[Inputs, Refs]):
    assert not await has_facts(**case.inputs.model_dump())
