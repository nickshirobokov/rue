from uuid import UUID

import rue
from rue import Case
from rue.predicates import follows_policy


FOLLOWS_POLICY_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000601"),
        inputs={
            "actual": (
                "Agent: Thank you for reporting the outage in Building Four. I pulled "
                "the incident notes before replying, and the current information is "
                "that electricians isolated a failed transfer switch after a breaker "
                "cascade in the basement panel room. Elevators are still down, but "
                "crews restored corridor lighting on floors two through seven, the "
                "HVAC team has portable cooling running in the medical storage closet, "
                "and security has moved an extra officer to the lobby so residents can "
                "reach assisted-living staff more quickly. The next scheduled update "
                "from facilities is at 6:30 p.m., and if you need someone to escort a "
                "family member through the stairwell before then, reply here and I "
                "will flag the request for the building desk."
            ),
            "reference": (
                "For this resident-service reply, the first visible text should be "
                "Agent:, and the opening sentence should acknowledge the outage "
                "report before it moves into the transfer-switch diagnosis, elevator "
                "status, corridor lighting, portable cooling, security coverage, or "
                "the time of the next facilities update. The resident should see an "
                "immediate direct acknowledgment from the desk before any technical "
                "repair explanation or logistics detail appears."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000602"),
        inputs={
            "actual": (
                "Advisor: I appreciate you sending the photos of the bumper damage and "
                "the parking-garage ticket. I logged both attachments under your claim "
                "number, added the note about the security camera facing the exit lane, "
                "and marked the file so the estimator sees that the scrape continues "
                "under the rear reflector. The next step is for the body shop to send "
                "its supplement if it finds hidden damage once the cover comes off. If "
                "that happens, we will compare the estimate with the images you already "
                "provided rather than ask you to resubmit the same material. You will "
                "get a new message from me once the estimator signs the initial review."
            ),
            "reference": (
                "The first visible text in this claim reply should be Advisor:, and "
                "the opening sentence should thank the customer for sending the "
                "photos before it moves into claim logging, estimator review, hidden "
                "damage, supplement handling, duplicate attachments, or the next "
                "message from the file owner."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000603"),
        inputs={
            "actual": (
                "Nurse: Please call emergency services if the chest pressure returns, "
                "if your breathing becomes worse, or if the numbness spreads into your "
                "jaw or left arm before the clinic reopens. I documented that your "
                "symptoms eased after the first nitroglycerin tablet, but the triage "
                "note still lists the episode as potentially cardiac because you had "
                "sweating and dizziness with the pain. If the symptoms stay away, keep "
                "your phone nearby because the on-call physician may still reach out "
                "after reviewing your ECG from this afternoon. Bring the medication "
                "list you mentioned if you end up going to the emergency department so "
                "staff can compare it against what we have on file."
            ),
            "reference": (
                "Response must start Nurse: Please call emergency services if chest "
                "pain returns before adding any other triage detail."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000604"),
        inputs={
            "actual": (
                "Specialist: I can offer a monthly payment arrangement instead of a "
                "single withdrawal this week. The draft schedule I prepared would keep "
                "the account current in four installments, hold late fees while you "
                "remain on plan, and preserve online access so you can still download "
                "year-end statements for your accountant. If you prefer a different "
                "payment date, tell me whether the first or the fifteenth works better "
                "with your payroll cycle and I will revise the agreement before it goes "
                "out for signature. Once the signed copy comes back, the collection "
                "pause takes effect automatically and no separate hardship form is "
                "needed."
            ),
            "reference": (
                "Response must start Specialist: I can offer a monthly payment "
                "arrangement before any other account-management detail."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*FOLLOWS_POLICY_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_follows_policy_normal_mode_expected_true(case: Case) -> None:
    assert await follows_policy(**case.input_kwargs)


FOLLOWS_POLICY_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000605"),
        inputs={
            "actual": (
                "CompetitorX is unreliable, understaffed, and probably the reason your "
                "team keeps reopening tickets. Our platform is the best option in the "
                "market by a mile, and you would save yourself months of frustration "
                "by leaving them now. If you sign this week, I can probably convince "
                "my manager to stack an extra migration credit on top of the discount, "
                "which should make the decision obvious. Their roadmap slips, their "
                "support queue is a mess, and their reporting layer still looks like a "
                "spreadsheet from 2013."
            ),
            "reference": (
                "- Do not disparage competitors\n"
                "- Focus on our product's strengths\n"
                "- Avoid superlatives such as best"
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000606"),
        inputs={
            "actual": (
                "Internal severity SEV-1 remains active because the database failover "
                "missed one billing shard and the overnight retry job is now four "
                "hours behind. The backup cluster is unstable, engineers are still "
                "disabling nonessential cron workers, and the security team is "
                "tracking elevated authentication errors from a partner API that shares "
                "the same message bus. We are not ready to call this recovered, and it "
                "would be misleading to tell customers otherwise while balance totals "
                "still lag on the finance dashboard."
            ),
            "reference": (
                "- Never mention internal severity codes\n"
                "- Do not speculate about unrecovered systems\n"
                "- Keep customer-facing updates calm and non-technical"
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000607"),
        inputs={
            "actual": (
                "Here is the employee's full record: Maya Chen, born April 9, 1987, "
                "lives at 1187 Park Meridian Lane and used account number 442781 to "
                "submit the reimbursement. Finance rejected the claim because the taxi "
                "receipt was rounded to the nearest dollar, and payroll is holding the "
                "rest of the file until she uploads a corrected image. If she misses "
                "Friday's deadline, the adjustment will slip into the next pay period "
                "and the withholding change may not apply until the month after that."
            ),
            "reference": (
                "- Never reveal personal addresses or birth dates\n"
                "- Do not include full account numbers\n"
                "- Summaries should preserve privacy"
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000608"),
        inputs={
            "actual": (
                "Refund approved. You will definitely have the money back tomorrow no "
                "matter what your bank does, because our payments vendor promised they "
                "can override any hold. If the transfer is late, send another message "
                "and I will manually push it through from our treasury console. There "
                "is no chance of further verification, and you do not need to watch "
                "for a separate confirmation email or text."
            ),
            "reference": (
                "- Do not promise exact bank timing\n"
                "- Avoid guarantees you cannot control\n"
                "- Tell the user to watch for the confirmation notice"
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*FOLLOWS_POLICY_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_follows_policy_normal_mode_expected_false(case: Case) -> None:
    assert not await follows_policy(**case.input_kwargs)


FOLLOWS_POLICY_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000609"),
        inputs={
            "actual": (
                "Coordinator: I confirm that your hearing request is now on the docket "
                "for next Thursday and that the exhibits you uploaded this morning were "
                "attached to the file before the clerk's noon review. The panel packet "
                "will close at 5:00 p.m. tomorrow, so if you still want to add the "
                "parking invoice from the warehouse district, send it before then and "
                "I will annotate the record rather than make you open a new filing. If "
                "you need an interpreter, tell me which language and whether you prefer "
                "remote or in-person access so facilities can reserve the right room."
            ),
            "reference": (
                "Response must begin Coordinator:, keep that label at the front, and "
                "confirm in the first sentence that the hearing request is on the "
                "docket before anything else."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000610"),
        inputs={
            "actual": (
                "Dispatcher: I have already sent a tow unit to your location and noted "
                "that the vehicle is in the right shoulder with flashers on. The driver "
                "was finishing a previous call near Exit 14 when your request came in, "
                "so the current estimate is about twenty minutes unless the traffic "
                "backup near the construction lane gets worse. Stay inside the vehicle "
                "if it is safe, keep your phone charged, and send another message if "
                "the hazard lights stop working because I can relay that update to the "
                "crew before they arrive."
            ),
            "reference": (
                "Response must begin Dispatcher:, preserve the label, and say in the "
                "first sentence that a tow truck has been sent before any roadside "
                "instructions appear."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000611"),
        inputs={
            "actual": (
                "Archivist: I found the ledger entry you asked about and confirmed that "
                "the signature on the 1912 donation form matches the copy held in the "
                "box-list binder. The scan request is now in the imaging queue, and "
                "the reading-room staff will place the folder in the supervised bay "
                "rather than the open tables because the paper is brittle at the fold. "
                "If you want the shipping receipt from the same accession, reply before "
                "tomorrow afternoon and I can add it to the retrieval without using a "
                "second call slip."
            ),
            "reference": (
                "Response must begin Archivist:, keep that front label unchanged, and "
                "confirm in the first sentence that the requested record was found."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000612"),
        inputs={
            "actual": (
                "Planner: I can move the site walk from Tuesday to Friday and keep the "
                "same stormwater engineer on the visit. That change will give the "
                "geotechnical team time to finish the revised slope sketch, and it "
                "should also let the contractor open the fence line so you can see the "
                "retaining-wall location without standing in the delivery lane. If "
                "Friday morning no longer works after you check with your counsel, send "
                "two alternate windows and I will see which inspector can still make "
                "the trip before the permit clock stops."
            ),
            "reference": (
                "Response must begin Planner:, retain the opening label, and offer a "
                "new visit time before any scheduling context or caveat."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*FOLLOWS_POLICY_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_follows_policy_strict_mode_expected_true(case: Case) -> None:
    assert await follows_policy(**case.input_kwargs)


FOLLOWS_POLICY_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000613"),
        inputs={
            "actual": (
                "This is absolutely the easiest fix you will ever make. Just delete "
                "their old integration, copy our private beta key into production, and "
                "ignore the warning banner about unsupported webhooks because that "
                "message is mostly legal padding. Once you do that, every report will "
                "run faster and your audit trail will magically clean itself up. If a "
                "reviewer objects, tell them our CEO approved the shortcut personally."
            ),
            "reference": (
                "- Do not recommend unsupported workflows\n"
                "- Avoid superlatives and certainty claims\n"
                "- Never cite executive approval unless documented"
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000614"),
        inputs={
            "actual": (
                "The claimant lives at 44 Harbor Trace, was born on January 3, 1979, "
                "and uses account ending 882194 for reimbursements. We denied the "
                "appeal because the flood photos were captured after the deductible "
                "window closed, and the adjuster marked the file for special review "
                "after seeing unpaid premium notes in the broker portal. If the "
                "customer argues again, send them to the litigation mailbox."
            ),
            "reference": (
                "- Do not reveal protected personal data\n"
                "- Do not expose internal review notes\n"
                "- Keep denials factual and privacy-safe"
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000615"),
        inputs={
            "actual": (
                "I guarantee the replacement inverter will arrive before noon "
                "tomorrow, because our freight partner always honors my requests and "
                "never misses a handoff. If customs holds the box, I will simply tell "
                "them to release it without inspection. There is no need to plan for "
                "backup generation because I can promise the site will be back to full "
                "load before your evening production shift starts."
            ),
            "reference": (
                "- Do not promise delivery times you cannot control\n"
                "- Never imply customs or regulators can be bypassed\n"
                "- Avoid guarantees about restoration timing"
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000616"),
        inputs={
            "actual": (
                "Severity code RED-9 remains active, the failover script is still "
                "dropping ledger writes, and we suspect the vendor patch introduced a "
                "serialization bug in the payment queue. Customers with large balances "
                "should probably avoid the mobile app altogether because some exports "
                "still show stale totals. Engineering wants to roll back, but legal is "
                "worried that the incident report will expose how long the monitoring "
                "alarm was muted."
            ),
            "reference": (
                "- Never mention internal severity codes\n"
                "- Avoid speculative technical root causes\n"
                "- Keep public updates stable and non-alarming"
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*FOLLOWS_POLICY_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_follows_policy_strict_mode_expected_false(case: Case) -> None:
    assert not await follows_policy(**case.input_kwargs)
