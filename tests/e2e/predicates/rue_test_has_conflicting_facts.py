# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import has_conflicting_facts

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


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

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means at least one fact in the actual
        document conflicts with at least one fact in
        the reference document. False means the two
        documents contain no conflicting facts.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:msa_start_date_conflict_very_easy"
        ),
        metadata={
            "slug": "msa_start_date_conflict_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Procurement summary for the Atlas Analytics renewal:

        Legal approved the master services agreement on January 10, and the
        operations copy states that service begins on January 15, 2026. The initial
        term is twelve months, invoices will be sent monthly, and the signed price
        remains $18,000 for the year. Customer success was asked to schedule
        onboarding during the week of January 19.
        """,
            reference="""
        Redlined version of the Atlas Analytics agreement:

        The master services agreement becomes effective on March 1, 2026. The first
        term lasts twelve months, invoicing is monthly, and total annual fees are
        $18,000.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:checkout_only_cause_conflict_easy"
        ),
        metadata={
            "slug": "checkout_only_cause_conflict_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Final postmortem draft:

        The seven-minute checkout outage on April 14 was caused only by the payment
        gateway timeout spike that started after the upstream provider rolled new
        firewall rules. The incident commander explicitly wrote that no internal
        queueing or retry behavior contributed to customer-facing failures. Once the
        provider reverted the firewall change, checkout latency normalized without
        any code deployment on our side.
        """,
            reference="""
        Incident review circulated by platform engineering:

        The April 14 checkout outage had two causes. The payment gateway began
        timing out after an upstream firewall change, and a misconfigured internal
        retry worker amplified the problem by hammering the gateway during the same
        seven-minute window. The review says both conditions contributed to the user
        impact.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:checkout_only_cause_conflict_medium"
        ),
        metadata={
            "slug": "checkout_only_cause_conflict_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Revised postmortem summary:

        The April 14 checkout outage is attributed entirely to the payment gateway
        timeout spike that followed the upstream firewall change. The incident
        commander wrote that internal retry behavior was noisy during triage but
        not a contributing cause of the customer-facing failure.

        Once the provider rolled back the rule change, checkout latency normalized
        without any deployment on our side.
        """,
            reference="""
        Incident review circulated by platform engineering:

        The April 14 checkout outage had two causes. The payment gateway began
        timing out after an upstream firewall change, and a misconfigured internal
        retry worker amplified the problem by hammering the gateway during the same
        seven-minute window. The review says both conditions contributed to the user
        impact.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:civic_listing_subset_no_conflict_very_easy",
        ),
        metadata={
            "slug": "civic_listing_subset_no_conflict_very_easy",
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
            NAMESPACE_URL,
            f"{__name__}:titan_losses_non_conflict_open_world_easy",
        ),
        metadata={
            "slug": "titan_losses_non_conflict_open_world_easy",
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
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:titan_losses_non_conflict_open_world_medium",
        ),
        metadata={
            "slug": "titan_losses_non_conflict_open_world_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Prepared remarks from the quarterly review:

        In Q3 the Titan recovery program produced close to a billion dollars in
        losses, most of it in the premium line. Leadership tied the return wave to
        the early camera module failure and then mentioned several other hardware
        problems, including a battery-swelling batch and intermittent antenna
        faults, that piled on service credits.
        """,
            reference="""
        Poor returns on the Titan premium phone were driven by camera problems and
        speaker defects, and the issue hit the company hard financially.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:rent_amount_conflict_very_easy"),
        metadata={
            "slug": "rent_amount_conflict_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Leasing confirmation email:

        Lena Ortiz accepted unit 4B at 214 Marigold Court for $2,450 per month. The
        move-in date is September 1, 2025, one covered parking stall is included,
        and the existing security deposit rolls over from the prior lease.
        """,
            reference="""
        Pricing summary prepared for accounting:

        Lena Ortiz is transferring into unit 4B at 214 Marigold Court on September
        1, 2025. The monthly rent for the new lease is $2,590, and one covered
        parking stall is included.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:dessert_preference_composition_conflict_easy",
        ),
        metadata={
            "slug": "dessert_preference_composition_conflict_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Expense-review note from the client dinner:

        At Friday's closing dinner, Leo ordered the tiramisu after the server read
        out the dessert specials. Nadia told the waiter she wanted the same dessert
        Leo was getting because she did not want to decide twice that night. The
        receipt shows two desserts on the table before coffee arrived.
        """,
            reference="""
        Short write-up from the same Friday dinner:

        Nadia did not eat tiramisu at the client dinner. She skipped dessert and
        only had coffee while the others ordered sweets.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:dessert_preference_composition_conflict_medium",
        ),
        metadata={
            "slug": "dessert_preference_composition_conflict_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Expense note from the client dinner:

        At Friday's closing dinner, Leo ordered tiramisu after the server read the
        dessert specials. Nadia told the waiter she wanted the same thing Leo was
        having because she was too tired to compare options. The table receipt
        later showed two desserts before coffee, and one was entered just after
        Nadia changed her order.
        """,
            reference="""
        Short write-up from the same Friday dinner:

        Nadia did not eat tiramisu at the client dinner. She skipped dessert and
        only had coffee while the others ordered sweets.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:beacon_release_extra_feature_no_conflict_very_easy",
        ),
        metadata={
            "slug": "beacon_release_extra_feature_no_conflict_very_easy",
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
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:introduction_and_name_not_conflict_easy"
        ),
        metadata={
            "slug": "introduction_and_name_not_conflict_easy",
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
        The new support hire's name is Roger Hale. He will be working on the returns
        queue.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:introduction_and_name_not_conflict_medium",
        ),
        metadata={
            "slug": "introduction_and_name_not_conflict_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Orientation recap from the support manager:

        During Monday's orientation, the new support hire introduced himself as
        Roger Hale and said he would spend his first two shifts shadowing the
        returns queue before rotating into the broader support schedule. The
        assignment sheet on the projector still labeled the role simply as customer
        support, and he thanked the room for helping him get his laptop working
        before the session started.
        """,
            reference="""
        The new support hire's name is Roger Hale. He will be working on the returns
        queue.
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
async def test_has_conflicting_facts_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await has_conflicting_facts(**case.inputs.model_dump())


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
    assert not await has_conflicting_facts(**case.inputs.model_dump())


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
    assert await has_conflicting_facts(**case.inputs.model_dump())


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
    assert not await has_conflicting_facts(**case.inputs.model_dump())
