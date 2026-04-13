# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import matches_writing_style

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


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

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


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


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:plain_ops_email_style_very_easy"),
        metadata={
            "slug": "plain_ops_email_style_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Team,

        Facilities is resetting the second-floor seating map on Monday. Please clear
        monitors, keyboards, and personal items from desks 2A through 2M by 6 p.m.
        Friday so the movers can swap docking stations before the contractor arrives.
        If you keep paper files in a pedestal, lock the drawer and leave the key
        with the office desk. The temporary quiet room will be conference B from
        Monday through Wednesday. Send exceptions to workplace@northpass.example by
        noon tomorrow.

        Thanks,
        Nina
        """,
            reference="""
        Team,

        Finance is closing the May books on Monday. Please submit vendor invoices
        over $500 by 3 p.m. Friday and add the project code in the comment field so
        accounting does not have to chase corrections next week. If an invoice is
        still waiting on approval, leave a note in the tracker instead of sending a
        separate email thread. Late submissions will move to the June close.

        Thanks,
        Marco
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:terse_engineering_voice_easy"),
        metadata={"slug": "terse_engineering_voice_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        Release cutover notes

        1. Freeze deploys at 21:45.
        2. Drain the queue before touching workers.
        3. If smoke tests fail, roll back first and explain later.

        Keep updates short. Post the exact error text, the impacted service, and the
        next action. Do not pad status messages with optimism. If you do not know the
        cause yet, say that directly and move to the next check.
        """,
            reference="""
        Pager handoff for Saturday

        Cache flush is already done. API pods are stable. If login latency crosses
        400 milliseconds, revert the image and reopen the bridge. Send one update
        with the metric, the suspected change, and the rollback state. Skip
        commentary until the graph settles. Precision matters more than reassurance
        during the first ten minutes of an incident.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:terse_engineering_voice_medium"),
        metadata={
            "slug": "terse_engineering_voice_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        DNS cutover notes

        1. Freeze edits at 20:55.
        2. Lower TTL before moving traffic.
        3. If health checks wobble, send traffic back before debating root cause.

        Status updates should be plain and short. Lead with the metric, then the
        affected region, then the next command. If the cause is unclear, say
        unclear. One precise sentence beats three reassuring ones.
        """,
            reference="""
        Pager handoff for Saturday

        Cache flush is already done. API pods are stable. If login latency crosses
        400 milliseconds, revert the image and reopen the bridge. Send one update
        with the metric, the suspected change, and the rollback state. Skip
        commentary until the graph settles. Precision matters more than reassurance
        during the first ten minutes of an incident.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:plain_email_vs_ornate_note_very_easy"
        ),
        metadata={
            "slug": "plain_email_vs_ornate_note_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Hi team,

        We need to move tomorrow's planning session to 2:30 p.m. because the vendor
        demo is running long. The agenda stays the same, and I will send the updated
        Zoom link in the calendar invite. If you cannot make the new time, reply by
        noon so we can collect blockers in advance.

        Best,
        Lila
        """,
            reference="""
        Dearest colleagues,

        With a reluctant heart I must ask that we let tomorrow's gathering drift a
        little later into the afternoon, for our visiting presenters have stretched
        the day beyond its intended shape. Fear not: the noble agenda remains
        intact, and a fresh link shall arrive presently like a courier bearing calm
        tidings. Should the new hour prove impossible, send word before noon and we
        shall gather your concerns with the care they deserve.

        Warmest regards,
        Lila
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:tabloid_vs_regulatory_style_easy"),
        metadata={
            "slug": "tabloid_vs_regulatory_style_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Another commute, another circus. By 5:20 the northbound platform was a wall
        of elbows, hot air, and furious phone calls because the signs kept blinking
        nonsense while trains crawled in like they were apologizing for existing.
        Riders were guessing destinations, shouting over the speaker static, and
        treating every rumor from the far end of the track like breaking news.
        Calling this a service disruption almost flatters it.
        """,
            reference="""
        Between 17:00 and 19:00, the agency observed repeated signal faults on the
        northbound line. Riders should expect residual delays while crews validate
        platform annunciators and restore normal dispatch spacing. Station staff were
        instructed to issue manual boarding guidance where digital signage was
        unavailable. The agency will publish a root-cause summary after maintenance
        review is complete.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:tabloid_vs_regulatory_style_medium"
        ),
        metadata={
            "slug": "tabloid_vs_regulatory_style_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Evening service bulletin, if that is what we are calling this circus:

        Between 17:00 and 19:00 riders experienced "residual delays" while the
        northbound platform turned into a pressure cooker of elbows, dying phone
        batteries, and rumors moving faster than the trains. The signs blinked
        nonsense, every tunnel squeal sounded like a false alarm, and people were
        treating scraps of overheard conversation like emergency dispatches.

        Station staff did issue manual boarding guidance where digital signage was
        unavailable. It mostly looked like exhausted employees trying to direct a
        crowd that had already stopped believing anything on the loudspeaker.
        """,
            reference="""
        Between 17:00 and 19:00, the agency observed repeated signal faults on the
        northbound line. Riders should expect residual delays while crews validate
        platform annunciators and restore normal dispatch spacing. Station staff were
        instructed to issue manual boarding guidance where digital signage was
        unavailable. The agency will publish a root-cause summary after maintenance
        review is complete.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:warm_support_style_very_easy"),
        metadata={
            "slug": "warm_support_style_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Hi Jamie,

        I checked the shipment and I can see why the tracking page looked odd this
        morning. The package missed last night's handoff after the label was scanned
        twice at the local depot, so the carrier moved it to tonight's truck instead.
        Nothing is lost and you do not need to do anything on your side. I will keep
        an eye on the next scan and send you another note as soon as it starts
        moving again.

        Best,
        Rowan
        """,
            reference="""
        Hi Priya,

        I looked at the password-reset logs and found the reason the link kept
        bouncing you back to the sign-in page. The first email expired after your
        browser restored an older session, so the second request never had a clean
        token to work with. I have already issued a fresh reset from my side, and
        you should be able to finish the update without any extra steps. If anything
        still feels off, reply here and I will stay with it.

        Best,
        Rowan
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:chatty_forum_style_easy"),
        metadata={"slug": "chatty_forum_style_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        I finally got my sourdough starter back on track after a week of it acting
        like wet wallpaper paste. What helped was less mystery and more routine: I
        switched to a jar with straight sides, fed it at the same hour every day,
        and stopped dumping in random flours because somebody online swore rye would
        fix my life. Two steady feedings later it was rising again and smelling like
        yogurt instead of nail polish. If yours looks lazy, simplify before you try
        anything dramatic.
        """,
            reference="""
        My compost bin stopped smelling like a swamp once I quit trying every clever
        internet trick in the same weekend. I picked one spot with shade, started
        turning it on a schedule, and kept the browns-to-greens mix boring and
        consistent for a few days. That was enough to settle it down. If the pile is
        weird, I would try fewer experiments and more routine before buying another
        gadget.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:chatty_forum_style_medium"),
        metadata={"slug": "chatty_forum_style_medium", "difficulty": "medium"},
        inputs=Inputs(
            actual="""
        My tomato seedlings looked doomed right up until I stopped trying to solve
        them with twelve different internet tricks at once. I gave them more
        light, watered on an actual schedule, and quit swapping fertilizers every
        time somebody online promised a miracle. The fix ended up being annoyingly
        boring, which is usually how gardening goes for me.

        If yours are sulking, I would pick one routine and give it a few days
        before shopping for another gadget. I am still embarrassingly easy to
        convince that the clever hack will save me, and it almost never does.
        """,
            reference="""
        My compost bin stopped smelling like a swamp once I quit trying every clever
        internet trick in the same weekend. I picked one spot with shade, started
        turning it on a schedule, and kept the browns-to-greens mix boring and
        consistent for a few days. That was enough to settle it down. If the pile is
        weird, I would try fewer experiments and more routine before buying another
        gadget.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:formal_memo_vs_group_chat_very_easy"
        ),
        metadata={
            "slug": "formal_memo_vs_group_chat_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Human resources advisory:

        Effective July 1, unused floating holidays will no longer roll into the next
        calendar quarter. Employees should schedule any remaining balance through the
        standard leave tool before June 28. Managers are responsible for approving or
        rejecting requests within two business days so payroll records can be closed
        on time. Questions should be directed to hr-operations@northpass.example.
        """,
            reference="""
        anybody free for lunch after standup? i found a taco place near the office
        that does the weird crispy potato thing everyone keeps talking about. if
        we're doing it, let's leave right away because the line gets terrible by
        12:15 and i'm not waiting behind three different finance teams again.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:legalistic_vs_marketing_style_easy"
        ),
        metadata={
            "slug": "legalistic_vs_marketing_style_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Renewal clause excerpt:

        Upon commencement of each successive renewal term, the customer shall remain
        bound by the then-current service order unless either party delivers written
        notice of non-renewal no fewer than thirty days before expiration of the
        active term. Any approved change in seat volume shall be documented by
        amendment, and failure to use the full allotment shall not reduce fees owed
        during the renewal period.
        """,
            reference="""
        Renew with us and keep the momentum going. Your team can roll straight into
        the next year without setup headaches, surprise downtime, or a messy
        migration project. If you need more seats, we can grow with you fast, and if
        your plans change later, our account team will help you sort out the right
        package without the usual procurement drama.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL, f"{__name__}:legalistic_vs_marketing_style_medium"
        ),
        metadata={
            "slug": "legalistic_vs_marketing_style_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Service-order renewal provision:

        Upon expiration of the initial term, the agreement shall renew
        automatically for successive one-year periods unless either party delivers
        written notice of non-renewal no fewer than thirty days before the end of
        the then-current term. Any increase in seat volume shall require an
        executed amendment or other written authorization accepted by both parties.

        For the avoidance of doubt, unused capacity or delayed rollout shall not
        reduce fees otherwise due during a renewal term. For convenience only, the
        account team may send a plain-language reminder before renewal, but the
        controlling terms remain those stated here.
        """,
            reference="""
        Renew with us and keep the momentum going. Your team can roll straight into
        the next year without setup headaches, surprise downtime, or a messy
        migration project. If you need more seats, we can grow with you fast, and if
        your plans change later, our account team will help you sort out the right
        package without the usual procurement drama.
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
async def test_matches_writing_style_strict_false_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_writing_style(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_writing_style_strict_false_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_writing_style(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_writing_style_strict_true_expected_true(
    case: Case[Inputs, Refs],
):
    assert await matches_writing_style(**case.inputs.model_dump())


@rue.test.iterate.cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.test.iterate(2)
async def test_matches_writing_style_strict_true_expected_false(
    case: Case[Inputs, Refs],
):
    assert not await matches_writing_style(**case.inputs.model_dump())
