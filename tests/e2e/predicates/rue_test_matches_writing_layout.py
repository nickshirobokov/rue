# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import matches_writing_layout

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must match
        the writing layout of the reference document.
        """,
    )
    reference: str = Field(
        description="""
        The reference document. For positive cases,
        the actual document must match the writing
        layout of this document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode — stricter layout matching.
        Not strict mode — more permissive layout
        matching.
        """,
    )

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual document matches the
        writing layout of the reference document.
        False means the actual document does not
        match the writing layout of the reference
        document.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:email_layout_very_easy"),
        metadata={"slug": "email_layout_very_easy", "difficulty": "very_easy"},
        inputs=Inputs(
            actual="""
        Hi team,

        The contractor will start replacing the lobby flooring at 7:00 a.m.
        Wednesday, so please use the loading-dock entrance until noon. Deliveries
        are still fine, but reception will be moved to conference room A while the
        front desk is blocked off.

        Thanks,
        Nina
        """,
            reference="""
        Dear colleagues,

        Our finance auditors will be onsite Thursday morning, so please keep the
        shared filing cabinets unlocked until the review ends. If you have receipts
        from last month that still need coding, leave them on the labeled tray near
        the copier before 9:30 a.m.

        Best regards,
        Marco
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:incident_markdown_template_easy"),
        metadata={
            "slug": "incident_markdown_template_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        # Incident Summary

        ## Impact
        - Checkout requests returned 502 errors for seven minutes.
        - Roughly 18 percent of shoppers abandoned carts during the spike.

        ## Timeline
        - 09:14 UTC: alerts fired for elevated gateway latency.
        - 09:17 UTC: incident bridge opened and deploys frozen.
        - 09:21 UTC: upstream firewall rollback started.
        - 09:24 UTC: success rate recovered above baseline.

        ## Follow-up
        - Add synthetic checkout probes from two regions.
        - Review retry-worker limits before the next traffic campaign.
        """,
            reference="""
        # Incident Summary

        ## Impact
        - Mobile logins failed for about eleven minutes.
        - Support volume increased because users could not refresh sessions.

        ## Timeline
        - 22:03 PT: certificate rotation began.
        - 22:08 PT: login smoke tests failed on one ingress pool.
        - 22:14 PT: pods were recycled with the renewed certificate.
        - 22:19 PT: successful login checks confirmed recovery.

        ## Follow-up
        - Add a thirty-day expiry alert for production certificates.
        - Document the recovery command in the change template.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:incident_markdown_template_medium"
        ),
        metadata={
            "slug": "incident_markdown_template_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        # Incident Summary

        ## Impact
        - Checkout requests returned 502 errors for seven minutes.
        - Cart conversion dipped during the spike.
        - Support saw a short burst of payment-related complaints
          from merchants retrying checkout during the bridge.

        ## Timeline
        - 09:14 UTC: alerts fired for elevated gateway latency.
        - 09:17 UTC: incident bridge opened and deploys were frozen.
        - 09:21 UTC: upstream firewall rollback began after provider confirmation.
        - 09:24 UTC: success rate recovered above baseline.

        ## Follow-up
        - Add synthetic checkout probes from two regions.
        - Review retry-worker limits before the next traffic campaign.
        - Clean up the bridge template so the provider escalation step is easier to
          find at 2 a.m.
        """,
            reference="""
        # Incident Summary

        ## Impact
        - Mobile logins failed for about eleven minutes.
        - Support volume increased because users could not refresh sessions.

        ## Timeline
        - 22:03 PT: certificate rotation began.
        - 22:08 PT: login smoke tests failed on one ingress pool.
        - 22:14 PT: pods were recycled with the renewed certificate.
        - 22:19 PT: successful login checks confirmed recovery.

        ## Follow-up
        - Add a thirty-day expiry alert for production certificates.
        - Document the recovery command in the change template.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:flat_json_vs_nested_json_very_easy"
        ),
        metadata={
            "slug": "flat_json_vs_nested_json_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        {
          "name": "roger hale",
          "role": "support",
          "office": "phoenix"
        }
        """,
            reference="""
        {
          "user": {
            "name": "roger hale",
            "office": "phoenix"
          },
          "roles": ["support"]
        }
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:faq_vs_narrative_layout_easy"),
        metadata={"slug": "faq_vs_narrative_layout_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        FAQ

        Q: When will the lobby flooring work start?
        A: Contractors arrive at 7:00 a.m. Wednesday.

        Q: Which entrance should employees use?
        A: Use the loading-dock entrance until noon.

        Q: Where will reception sit during the work?
        A: Reception moves to conference room A.
        """,
            reference="""
        The contractor will start replacing the lobby flooring at 7:00 a.m.
        Wednesday. During the morning work window, employees should use the
        loading-dock entrance because the front desk area will be blocked. Reception
        will operate out of conference room A until the flooring crew clears the
        main entrance around noon.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:faq_vs_narrative_layout_medium"),
        metadata={
            "slug": "faq_vs_narrative_layout_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Access note for Wednesday morning

        1. Flooring work starts at 7:00 a.m. Wednesday.
        2. Use the loading-dock entrance until noon.
        3. Reception works from conference room A while the front desk is blocked.
        4. Couriers can still deliver, but they should follow the temporary side
           path.
        """,
            reference="""
        The contractor will start replacing the lobby flooring at 7:00 a.m.
        Wednesday. During the morning work window, employees should use the
        loading-dock entrance because the front desk area will be blocked. Reception
        will operate out of conference room A until the flooring crew clears the
        main entrance around noon.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:json_schema_same_very_easy"),
        metadata={
            "slug": "json_schema_same_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        {
          "incident": "checkout-outage",
          "severity": "high",
          "owner": "platform-core",
          "window_minutes": 7
        }
        """,
            reference="""
        {
          "incident": "certificate-rotation",
          "severity": "low",
          "owner": "edge-platform",
          "window_minutes": 19
        }
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:numbered_contract_layout_easy"),
        metadata={
            "slug": "numbered_contract_layout_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        1. Term. The initial service period begins on July 1, 2025 and ends on June
        30, 2026.

        2. Fees. Customer will pay $18,000 annually in monthly installments.

        3. Notice. Either party may decline renewal by giving thirty days' written
        notice before the current term expires.
        """,
            reference="""
        1. Term. The consulting period starts on October 15, 2025 and closes on
        October 14, 2026.

        2. Fees. Client will pay $42,000 over the term in quarterly installments.

        3. Notice. A party that does not wish to renew must provide written notice
        at least thirty days before expiration.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:numbered_contract_layout_medium"),
        metadata={
            "slug": "numbered_contract_layout_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        1. Term. The initial service period begins on July 1, 2025 and ends on June
        30, 2026.
           Renewal mechanics: any extension beyond that date is governed by the
           notice provision below.

        2. Fees. Customer will pay $18,000 annually in monthly installments.
           Invoice cadence: monthly.
           Late payment: does not change the installment structure.

        3. Notice. Either party may decline renewal by giving thirty days' written
        notice before the current term expires.
        """,
            reference="""
        1. Term. The consulting period starts on October 15, 2025 and closes on
        October 14, 2026.

        2. Fees. Client will pay $42,000 over the term in quarterly installments.

        3. Notice. A party that does not wish to renew must provide written notice
        at least thirty days before expiration.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:paragraph_vs_checklist_very_easy"),
        metadata={
            "slug": "paragraph_vs_checklist_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Please clear monitors, keyboards, and notebooks from desks 2A through 2M by
        6 p.m. Friday so the movers can swap docking stations before the contractor
        arrives Monday morning. If you keep paper files in a pedestal, lock the
        drawer and leave the key with the office desk.
        """,
            reference="""
        Workplace reset checklist

        - Clear monitors, keyboards, and notebooks from desks 2A through 2M.
        - Lock any pedestal drawers that contain paper files.
        - Leave drawer keys with the office desk before 6 p.m. Friday.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:section_order_difference_easy"),
        metadata={
            "slug": "section_order_difference_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        # Release Note

        ## Summary
        Beacon 2.1 shipped Tuesday morning after a short maintenance window.

        ## Impact
        Saved filters were unaffected and no billing migration ran.

        ## Timeline
        Deployment started at 09:00 UTC and user traffic resumed at 09:15 UTC.

        ## Next Steps
        Support will monitor export-related tickets for the rest of the week.
        """,
            reference="""
        # Release Note

        ## Summary
        Beacon 2.1 shipped Tuesday morning after a short maintenance window.

        ## Timeline
        Deployment started at 09:00 UTC and user traffic resumed at 09:15 UTC.

        ## Impact
        Saved filters were unaffected and no billing migration ran.

        ## Next Steps
        Support will monitor export-related tickets for the rest of the week.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:pseudo_heading_layout_difference_medium"
        ),
        metadata={
            "slug": "pseudo_heading_layout_difference_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        # Release Note

        ## Summary
        Beacon 2.1 shipped Tuesday morning after a short maintenance window and the
        bridge closed without extending downtime.

        **Timeline**
        Deployment started at 09:00 UTC and user traffic resumed at 09:15 UTC.

        ## Impact
        Saved filters were unaffected, no billing migration ran, and support only
        expects minor export follow-up.

        ## Next Steps
        Support will monitor export-related tickets for the rest of the week, and
        engineering will clean up the backlog dashboard wording because the labels
        are still weird.
        """,
            reference="""
        # Release Note

        ## Summary
        Beacon 2.1 shipped Tuesday morning after a short maintenance window.

        ## Timeline
        Deployment started at 09:00 UTC and user traffic resumed at 09:15 UTC.

        ## Impact
        Saved filters were unaffected and no billing migration ran.

        ## Next Steps
        Support will monitor export-related tickets for the rest of the week.
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
async def test_matches_writing_layout_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_writing_layout(**case.inputs.model_dump())


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_writing_layout_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_writing_layout(**case.inputs.model_dump())


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_writing_layout_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_writing_layout(**case.inputs.model_dump())


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_matches_writing_layout_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_writing_layout(**case.inputs.model_dump())
