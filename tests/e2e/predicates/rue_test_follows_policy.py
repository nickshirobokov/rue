# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import follows_policy

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


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

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual text follows the policy
        described in the reference text. False means
        the actual text violates the policy described
        in the reference text.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:status_email_policy_very_easy"),
        metadata={
            "slug": "status_email_policy_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Hi Maya,

        Here is the warehouse migration status update you asked for this morning.

        - The migration finished at 09:15 UTC without extending the maintenance
          window.
        - Saved filters and customer billing records were unaffected during the
          rollout.
        - Support will watch export-related tickets through Friday and escalate any
          new pattern immediately.

        Thanks,
        Nina
        """,
            reference="""
        Write a client status email that includes a greeting, exactly three bullet
        points in the body, and a signoff that starts with "Thanks,". The email must
        not mention prices, fees, or dollar amounts.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:incident_json_policy_easy"),
        metadata={"slug": "incident_json_policy_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        {
          "incident": "checkout-outage-apr14",
          "severity": "high",
          "customer_impact": "checkout returned 502 errors for seven minutes and cart conversion dropped during the spike",
          "timeline": [
            {
              "time": "09:14 UTC",
              "event": "alerts fired for elevated payment gateway latency"
            },
            {
              "time": "09:17 UTC",
              "event": "incident bridge opened and deploys were frozen"
            },
            {
              "time": "09:24 UTC",
              "event": "success rate recovered after the upstream firewall rollback"
            }
          ],
          "next_steps": [
            "add synthetic checkout probes from two regions",
            "review retry-worker limits before the next traffic campaign"
          ]
        }
        """,
            reference="""
        Return valid JSON with exactly these top-level keys: incident, severity,
        customer_impact, timeline, and next_steps. The severity value must be
        lowercase text. The timeline field must be an array of objects, and every
        object in that array must contain both time and event keys.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:incident_json_policy_medium"),
        metadata={
            "slug": "incident_json_policy_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        {
          "incident": "checkout-outage-apr14",
          "severity": "high",
          "customer_impact": "checkout returned 502 errors for seven minutes, cart conversion dipped during the spike, and support saw a short burst of worried chats right after 09:17 UTC",
          "timeline": [
            {
              "time": "09:14 UTC",
              "event": "alerts fired for elevated payment gateway latency"
            },
            {
              "time": "09:17 UTC",
              "event": "incident bridge opened; deploys were frozen",
              "owner": "platform-oncall"
            },
            {
              "time": "09:21 UTC",
              "event": "upstream firewall rollback began after the provider confirmed the bad rule push"
            },
            {
              "time": "09:24 UTC",
              "event": "success rate recovered and checkout tests stopped failing"
            }
          ],
          "next_steps": [
            "add synthetic checkout probes from two regions",
            "review retry-worker limits before the next traffic campaign",
            "tighten the bridge checklist so upstream dependency changes are called out faster"
          ]
        }
        """,
            reference="""
        Return valid JSON with exactly these top-level keys: incident, severity,
        customer_impact, timeline, and next_steps. The severity value must be
        lowercase text. The timeline field must be an array of objects, and every
        object in that array must contain both time and event keys.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:status_email_policy_violation_very_easy"
        ),
        metadata={
            "slug": "status_email_policy_violation_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Hi Maya,

        Here is the warehouse migration status update you asked for this morning.

        - The migration finished at 09:15 UTC without extending the maintenance
          window.
        - Saved filters and customer billing records were unaffected during the
          rollout.
        - Support will watch export-related tickets through Friday.
        - The upgraded analytics add-on still costs $99 per workspace each month.

        Thanks,
        Nina
        """,
            reference="""
        Write a client status email that includes a greeting, exactly three bullet
        points in the body, and a signoff that starts with "Thanks,". The email must
        not mention prices, fees, or dollar amounts.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:incident_json_policy_violation_easy"
        ),
        metadata={
            "slug": "incident_json_policy_violation_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        {
          "incident": "checkout-outage-apr14",
          "severity": "HIGH",
          "customer_impact": "checkout returned 502 errors for seven minutes and cart conversion dropped during the spike",
          "timeline": [
            {
              "time": "09:14 UTC",
              "event": "alerts fired for elevated payment gateway latency"
            },
            {
              "time": "09:17 UTC",
              "detail": "incident bridge opened and deploys were frozen"
            }
          ]
        }
        """,
            reference="""
        Return valid JSON with exactly these top-level keys: incident, severity,
        customer_impact, timeline, and next_steps. The severity value must be
        lowercase text. The timeline field must be an array of objects, and every
        object in that array must contain both time and event keys.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:incident_json_policy_violation_medium"
        ),
        metadata={
            "slug": "incident_json_policy_violation_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        {
          "incident": "checkout-outage-apr14",
          "severity": "high",
          "customer_impact": "checkout returned 502 errors for seven minutes and support saw a burst of chat complaints",
          "timeline": [
            {
              "time": "09:14 UTC",
              "event": "alerts fired for elevated payment gateway latency"
            },
            {
              "time": "09:17 UTC",
              "event": "incident bridge opened and deploys were frozen"
            },
            {
              "time": "09:24 UTC",
              "event": "success rate recovered after the upstream firewall rollback"
            }
          ],
          "nextSteps": [
            "add synthetic checkout probes from two regions",
            "review retry-worker limits before the next traffic campaign"
          ]
        }
        """,
            reference="""
        Return valid JSON with exactly these top-level keys: incident, severity,
        customer_impact, timeline, and next_steps. The severity value must be
        lowercase text. The timeline field must be an array of objects, and every
        object in that array must contain both time and event keys.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:formal_email_policy_very_easy"),
        metadata={
            "slug": "formal_email_policy_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Dear Jordan,

        I am writing to confirm that the facilities contractor will begin the lobby
        flooring replacement at 7:00 a.m. on Wednesday. Please use the loading-dock
        entrance until noon while the front desk area is inaccessible. Reception
        staff will work from conference room A during the morning construction
        window. If your team expects a visitor who may need assistance finding the
        alternate entrance, please notify workplace operations in advance.

        Sincerely,
        Nina Patel
        """,
            reference="""
        Write a formal and concise email. Include a greeting and a signoff. Do not
        mention prices, fees, discounts, or any other pricing information.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:markdown_sections_policy_easy"),
        metadata={
            "slug": "markdown_sections_policy_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        ## Summary

        The migration window for Beacon 2.1 ran from 09:00 to 09:15 UTC on Tuesday
        morning and completed without extending user-facing downtime.

        ## Risks

        Support may still see a few delayed export jobs because the backlog is being
        reprocessed in smaller batches. No billing data was touched during the
        release, so the remaining risk is operational rather than financial.

        ## Next Steps

        - Monitor export-related tickets through Friday.
        - Review the backlog drain metrics in tomorrow's standup.
        """,
            reference="""
        Produce Markdown with exactly three section headings titled Summary, Risks,
        and Next Steps, in that order. Do not use numbered lists anywhere in the
        document. The text must explicitly mention the migration window.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:markdown_sections_policy_medium"),
        metadata={
            "slug": "markdown_sections_policy_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        ## Summary

        The migration window for Beacon 2.1 opened at 09:00 UTC and closed at
        09:15 UTC on Tuesday morning. The rollout stayed inside that window even
        though the backlog monitor looked a little weird for the first couple of
        minutes.

        ## Risks

        Export jobs are still draining in smaller batches, and step 2 in the bridge
        checklist still points responders to the older dashboard. No billing data
        moved during the release, which keeps the remaining risk operational rather
        than financial.

        ## Next Steps

        - Keep an eye on export-related tickets through Friday.
        - Review backlog drain metrics in tomorrow's standup.
        - Clean up the bridge notes because the timestamp typo is already confusing
          people.
        """,
            reference="""
        Produce Markdown with exactly three section headings titled Summary, Risks,
        and Next Steps, in that order. Do not use numbered lists anywhere in the
        document. The text must explicitly mention the migration window.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:lowercase_names_policy_violation_very_easy",
        ),
        metadata={
            "slug": "lowercase_names_policy_violation_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        alice met Bob in the lobby after standup and handed over the signed vendor
        packet. They reviewed the renewal notes, confirmed the office address, and
        agreed to send the final countersignature before the legal cutoff on Friday.
        """,
            reference="""
        Every personal name in the text must be lowercase. The text must not mention
        prices or dollar amounts.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:exact_json_keys_policy_violation_easy"
        ),
        metadata={
            "slug": "exact_json_keys_policy_violation_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        {
          "name": "roger hale",
          "email": "roger.hale@example.com",
          "role": "support"
        }
        """,
            reference="""
        Return valid JSON with exactly two top-level keys: name and email. No extra
        top-level keys are allowed, even if the additional fields are harmless.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:exact_json_keys_policy_violation_medium"
        ),
        metadata={
            "slug": "exact_json_keys_policy_violation_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        {
          "Name": "roger hale",
          "email": "roger.hale@example.com"
        }
        """,
            reference="""
        Return valid JSON with exactly two top-level keys: name and email. No extra
        top-level keys are allowed, even if the additional fields are harmless.
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
async def test_follows_policy_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await follows_policy(**case.inputs.model_dump())


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
    assert not await follows_policy(**case.inputs.model_dump())


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
    assert await follows_policy(**case.inputs.model_dump())


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
    assert not await follows_policy(**case.inputs.model_dump())
