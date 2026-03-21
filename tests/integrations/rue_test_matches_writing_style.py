from uuid import UUID

import rue
from rue import Case
from rue.predicates import matches_writing_style


MATCHES_WRITING_STYLE_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000801"),
        sut_input_values={
            "actual": (
                "Friday?"
            ),
            "reference": (
                "Dear Maya,\n\nPlease accept this letter as formal confirmation that "
                "Friday morning remains the scheduled window for the retaining-wall "
                "inspection. The revised slope sketch has been returned, the wall line "
                "has been corrected, and the stormwater engineer remains available "
                "should you still wish to review the fence line before the packet "
                "closes. Kindly advise if you require the supporting documents.\n\n"
                "Yours faithfully,\nMaya"
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000802"),
        sut_input_values={
            "actual": (
                "Hey team, the ferry photos are in. I tagged the heritage-wrap shots, "
                "parked the duplicates, and flagged the two frames where the color "
                "looks different in the light."
            ),
            "reference": (
                "Dear team, the ferry photos finally landed in the archive drive. I "
                "tagged the heritage-wrap weekend shots, pushed the duplicate dock "
                "images into a holding folder, and left a note on the two frames where "
                "the livery looks different because of the light. Nothing formal here; "
                "I just wanted the sorting done before the museum volunteer logs in. "
                "Please ignore the rough filenames from the camera card, because I was "
                "moving faster than I should have when the dock office started calling "
                "about tomorrow's access window. If anyone spots another angle where "
                "the wrap reads differently from the weekday livery, drop a comment in "
                "the folder and I will clean up the captions later tonight."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000803"),
        sut_input_values={
            "actual": (
                "Hi Sam, did the clinic desk ever send the corrected estimate? I have "
                "the photos and ticket, but I do not want to close the file if the "
                "body shop is still sitting on a supplement."
            ),
            "reference": (
                "Dear Sam, did the clinic desk ever send the corrected estimate? I "
                "have the photos, the garage ticket, and the adjuster note, but I "
                "would rather not close the thread if the body shop is still sitting "
                "on a supplement. Send it over when you see it and I will clean up the "
                "claim file. I am trying to keep this light because the customer has "
                "already repeated the same story three times, and I would rather not "
                "send another stiff note that sounds like a template. If the supplement "
                "is still missing by lunch, I will call the shop directly instead of "
                "waiting for another portal refresh."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000804"),
        sut_input_values={
            "actual": (
                "Hey Priya, I found the ledger page and put it in the supervised bay. "
                "If you want the shipping receipt too, say the word and I will pull it "
                "with the next cart."
            ),
            "reference": (
                "Dear Priya, I found the ledger page and set it aside in the "
                "supervised bay because the fold is brittle. If you want the shipping "
                "receipt from the same accession, tell me before tomorrow afternoon and "
                "I will have it pulled with the next cart. I am keeping this informal "
                "because the reading-room staff already know the file and there is no "
                "reason to wrap a simple retrieval note in a ceremonial memo. If you "
                "end up needing the accession card as well, I can add it without "
                "opening a second request."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_STYLE_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_matches_writing_style_normal_mode_expected_true(case: Case) -> None:
    assert await matches_writing_style(**case.sut_input_values)


MATCHES_WRITING_STYLE_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000805"),
        sut_input_values={
            "actual": (
                "Pursuant to Section 7.4 of the distribution agreement, the seller "
                "hereby notifies the purchaser that all representations concerning "
                "warehouse temperature integrity remain subject to documentary audit. "
                "No waiver shall be inferred from interim acceptance of goods, and the "
                "parties acknowledge that any remedial shipment will be conditioned on "
                "full preservation of inspection rights under the governing schedule."
            ),
            "reference": (
                "Move fast. Ship clean. Keep the line moving. Our new cold-chain stack "
                "cuts the wait, tightens the route, and gives your team the confidence "
                "to say yes before the dock goes quiet. Less lag. Fewer handoffs. More "
                "work done before sunrise."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000806"),
        sut_input_values={
            "actual": (
                "Field log, 04:18. Relay cabinet warm to the touch. Condensation on "
                "inner shield. Amber indicator observed during boot cycle. Terminal "
                "screws retorqued to spec. Event logger confirms successful reset. "
                "Crew cleared site at 04:37 after one final visual check of gasket "
                "seating and cable strain relief."
            ),
            "reference": (
                "Friends, history needs your help tonight. The depot archive holds the "
                "letters that taught this city who it was, and one more season of "
                "delay could leave irreplaceable paper at the mercy of damp walls and "
                "failing locks. Give now, share the campaign, and help us move the "
                "collection into a safe downtown home before another winter arrives."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000807"),
        sut_input_values={
            "actual": (
                "The procurement memorandum recommends awarding the accessibility "
                "testing contract to the lowest responsive bidder that met the screen-"
                "reader benchmark, keyboard-navigation threshold, and captioning "
                "deliverable schedule. Pricing analysis appears in Appendix C, vendor "
                "references appear in Appendix D, and the proposed notice to proceed "
                "is attached for chair review."
            ),
            "reference": (
                "Saturday belonged to the underdogs. Rain hammered the grandstand, the "
                "favorite missed two easy corners, and the local crew stole the race "
                "with a late surge that sent the infield into a wall of noise. Nobody "
                "will remember the forecasts now; they will remember the grit."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000808"),
        sut_input_values={
            "actual": (
                "Incident summary: power loss traced to transfer-switch failure in "
                "basement panel room. Corridor lighting restored on floors two through "
                "seven. Elevators remain unavailable. Portable cooling active in "
                "medical storage. Next facilities update scheduled for 18:30. Security "
                "assigned additional lobby coverage for assisted-living access."
            ),
            "reference": (
                "The future deserves cleaner motion. Step into the new commuter line "
                "and feel the quiet torque, the brighter cabin, the easy boarding, and "
                "the routes that finally connect where people already live. No drama. "
                "No fumes. Just a better trip waiting at the platform."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_STYLE_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_matches_writing_style_normal_mode_expected_false(case: Case) -> None:
    assert not await matches_writing_style(**case.sut_input_values)


MATCHES_WRITING_STYLE_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000809"),
        sut_input_values={
            "actual": (
                "Twenty minutes?"
            ),
            "reference": (
                "Dear Jordan:\n\nPlease accept this formal notice that the tow truck "
                "has been dispatched and should arrive in approximately twenty minutes. "
                "If the hazard lights fail before the driver reaches you, kindly reply "
                "at once so that I may amend the roadside log.\n\nRespectfully,\n"
                "Dispatch Office"
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000810"),
        sut_input_values={
            "actual": (
                "Hey Lena, the crate sheet is signed. Same cradle, same silica packs, "
                "papers under the right handle, and I would rather send it tonight "
                "than wait for the morning truck."
            ),
            "reference": (
                "Dear Lena, the registrar finally signed the outbound crate sheet. We "
                "kept the same foam cradle and silica packs, taped customs papers "
                "under the right handle, and left the courier packet in the lid sleeve. "
                "I would rather send it tonight than trust the morning truck. This is "
                "one of those quick museum notes that sits somewhere between a text "
                "message and a formal handoff letter, but it should tell you "
                "everything you need before the loader arrives. If the courier calls "
                "again about the weather, tell them the jar is already packed and the "
                "shock sensors are armed."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000811"),
        sut_input_values={
            "actual": (
                "Hey crew, the weather mast is back online. New cups are in, the "
                "ground tested clean, and the top beacon only looks different because "
                "it has a fresh lens."
            ),
            "reference": (
                "Dear crew, the weather mast is back online. The anemometer cups are "
                "new, the lightning ground tested clean, and the ladder cage was "
                "repainted before the rain arrived. If the top beacon looks different "
                "from the old photo set, it is the same lamp with a fresh lens rather "
                "than a missed repair. I know this reads more like a scribbled field "
                "letter than a maintenance bulletin, but the point is just to keep the "
                "photo archive from inventing a problem that does not exist. When the "
                "next shift checks the berm, they do not need another layer of "
                "paperwork."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000812"),
        sut_input_values={
            "actual": (
                "Hi Priya, I can move the site walk to Friday and keep the same "
                "engineer on it. That should give the geotech team enough time to "
                "finish the revised slope sketch."
            ),
            "reference": (
                "Dear Priya, I can move the site walk to Friday and keep the same "
                "stormwater engineer on it. That should give the geotech team enough "
                "time to finish the revised slope sketch and open the fence line so "
                "you can see the retaining wall without standing in the delivery lane. "
                "I am writing it this way because a chatty note is faster than another "
                "calendar invitation with half the context missing. If Friday changes "
                "again after counsel weighs in, send two alternate windows and I will "
                "rebuild the inspection chain."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_STYLE_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_matches_writing_style_strict_mode_expected_true(case: Case) -> None:
    assert await matches_writing_style(**case.sut_input_values)


MATCHES_WRITING_STYLE_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000813"),
        sut_input_values={
            "actual": (
                "Section 4.2 requires the buyer to preserve all inspection rights "
                "pending warehouse audit, and no interim acceptance of goods shall be "
                "construed as a waiver of temperature-integrity claims. Any remedial "
                "shipment remains contingent on documentary proof that cold-chain "
                "control failed during the carrier's custody period."
            ),
            "reference": (
                "Built for the rush. Tuned for the turn. The new commuter set slides "
                "into your morning with cleaner power, quieter cabins, and the kind of "
                "acceleration that makes the old timetable feel slow before the doors "
                "even close."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000814"),
        sut_input_values={
            "actual": (
                "Lab notebook entry: sample tray warped at 62.4 degrees Celsius. "
                "Operator repeated the measurement after recalibrating the probe and "
                "logged a second deviation under the same batch number. No further "
                "material released pending quality review."
            ),
            "reference": (
                "Dear neighbors, our riverfront theater has weathered another season "
                "of leaks and patched seats, but the curtain still rises because "
                "people like you refuse to let the building go dark. Donate tonight "
                "and help us keep music, drama, and school matinees alive for another "
                "generation."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000815"),
        sut_input_values={
            "actual": (
                "The policy memo recommends holding the rent increase below the "
                "insurance delta, sequencing elevator replacements before facade work, "
                "and preserving the deed-restricted senior campus through the next "
                "capital cycle. Draft notice language appears in Appendix B."
            ),
            "reference": (
                "Saturday's derby turned ugly, then glorious. Mud sprayed off the "
                "inside rail, three favorites tangled in the second bend, and the home "
                "stable found a path where nobody else could. It was loud, reckless, "
                "and unforgettable."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000816"),
        sut_input_values={
            "actual": (
                "Incident note: transfer switch failed in basement panel room. "
                "Temporary cooling active. Elevator service suspended. Additional lobby "
                "security posted. Next facilities update at 18:30. Residents requiring "
                "stair assistance should notify the desk before the next generator "
                "fuel check."
            ),
            "reference": (
                "The new line is clean, bright, and ready. Step aboard for quieter "
                "rides, simpler boarding, and the kind of route map that finally feels "
                "built around the city people actually use. Morning travel should not "
                "feel like a compromise."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_STYLE_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_matches_writing_style_strict_mode_expected_false(case: Case) -> None:
    assert not await matches_writing_style(**case.sut_input_values)
