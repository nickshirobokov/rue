from uuid import UUID

import rue
from rue import Case
from rue.predicates import matches_writing_layout


MATCHES_WRITING_LAYOUT_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000701"),
        inputs={
            "actual": (
                "Incident: Harbor Spur Relay Cabinet\n"
                "Status: Monitoring after overnight reset\n"
                "Owner: Rail Signals Night Crew\n"
                "Observed At: 05:48 local time\n"
                "Primary Note: Amber indicator seen during boot cycle before charging "
                "latched\n"
                "Follow-Up: Verify gasket seal, confirm event logger stamp, recheck "
                "terminal screws at next patrol\n"
                "Archive Flag: Keep the diagnostic photo pair with the maintenance "
                "record\n"
                "Dispatch Note: Do not replace unit unless color change occurs inside "
                "the same operating mode"
            ),
            "reference": (
                "# Harbor Spur relay-cabinet monitoring after the overnight reset by "
                "the night crew at 05:48"
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000702"),
        inputs={
            "actual": (
                "Case: Wildfire Business-Loss Mediation\n"
                "Stage: Post-mediation settlement notice\n"
                "Primary Contact: Claims Communications Desk\n"
                "Affected Group: 312 franchisees\n"
                "Open Item: Court approval of final papers\n"
                "Next Task: Extend phone hours and prepare returned-wire instructions\n"
                "Internal Concern: Prevent rumor screenshots from driving more inbound "
                "calls\n"
                "Banking Note: Returned-wire process must be attached to the FAQ"
            ),
            "reference": (
                "Wildfire business-loss mediation case now at the post-mediation "
                "settlement-notice stage for 312 franchisees under the claims "
                "communications desk with court approval still open, rumor control in "
                "the call queue, and returned-wire instructions queued for the FAQ."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000703"),
        inputs={
            "actual": (
                "Shipment: Outbound Astrolabe Loan Crate\n"
                "Carrier Window: Tonight's museum truck\n"
                "Packing Lead: Registrar on duty\n"
                "Internal Configuration: Foam cradle, silica packs, courier packet in "
                "lid sleeve\n"
                "Document Placement: Customs papers taped under right-side handle\n"
                "Risk Note: Watch repaired shoulder crack during unload\n"
                "Climate Note: Hold in conditioned bay until truck backs in\n"
                "Seal Check: Shock sensors armed before loader sign-off"
            ),
            "reference": (
                "Outbound astrolabe loan-crate shipment on tonight's museum truck with "
                "the registrar packing a foam cradle, silica packs, and a courier "
                "packet in the lid sleeve, customs papers under the right handle, the "
                "crate held in the conditioned bay, and a shoulder-crack warning for "
                "the unload."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000704"),
        inputs={
            "actual": (
                "Accession: Founder Family Correspondence\n"
                "Location: Supervised bay, downtown depot reading room\n"
                "Condition: Brittle fold at center seam\n"
                "Handling Rule: Keep off open tables\n"
                "Related Material: Shipping receipt can be pulled with next cart\n"
                "Staff Note: Reading-room team already alerted\n"
                "Verification: Signature matches binder copy\n"
                "Imaging Status: Scan request entered queue"
            ),
            "reference": (
                "Founder family correspondence accession in the supervised bay of the "
                "downtown depot reading room with a brittle center fold, a matching "
                "signature on file, a scan request already queued, shipping receipts "
                "available on the next cart pull, and the reading-room team already "
                "alerted."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_LAYOUT_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_matches_writing_layout_normal_mode_expected_true(case: Case) -> None:
    assert await matches_writing_layout(**case.input_kwargs)


MATCHES_WRITING_LAYOUT_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000705"),
        inputs={
            "actual": (
                '{\n'
                '  "incident": "basement transfer-switch failure",\n'
                '  "status": "partial recovery",\n'
                '  "impacts": ["elevators down", "portable cooling active"],\n'
                '  "next_update": "18:30",\n'
                '  "owner": "facilities command"\n'
                '}'
            ),
            "reference": (
                "## Building Outage Summary\n\n"
                "Power loss traced to transfer-switch failure in basement panel room.\n\n"
                "## Current Impacts\n"
                "- Elevators unavailable\n"
                "- Portable cooling active in medical storage\n\n"
                "## Next Update\n"
                "Facilities will post another notice at 18:30."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000706"),
        inputs={
            "actual": (
                "The policy memo recommends capping the rent increase below the "
                "insurance delta, sequencing elevator replacements before facade work, "
                "and preserving the deed-restricted senior campus through the next "
                "capital cycle. It closes with a paragraph on translation obligations "
                "for tenant notices and another on weatherization grant timing."
            ),
            "reference": (
                "1. Current rent recommendation\n"
                "2. Insurance premium pressure\n"
                "3. Elevator replacement plan\n"
                "4. Senior-campus deed restrictions\n"
                "5. Translation and notice obligations\n"
                "6. Weatherization grant timing"
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000707"),
        inputs={
            "actual": (
                "From: Claims Communications Desk\n"
                "To: Franchise Owners Group\n"
                "Subject: Settlement Notice Timeline\n"
                "Attachments: returned-wire instructions, FAQ, payment verification "
                "sheet"
            ),
            "reference": (
                "### Mediation Recap\n\n"
                "The settlement covers 312 franchisees and still requires court "
                "approval.\n\n"
                "### Operations Response\n\n"
                "Phone hours will be extended once notice goes out."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000708"),
        inputs={
            "actual": (
                "Q: Did the clinic desk send the corrected estimate?\n"
                "A: Not yet.\n"
                "Q: Do we have the garage ticket?\n"
                "A: Yes, filed with the photos.\n"
                "Q: Next step?\n"
                "A: Wait for the body-shop supplement."
            ),
            "reference": (
                "Dear Sam,\n\n"
                "I have the photos, the garage ticket, and the adjuster note, but I "
                "do not want to close the thread if the body shop is still sitting on "
                "a supplement. Send it when you see it and I will clean up the claim "
                "file.\n\n"
                "Best,\n"
                "Maya"
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_LAYOUT_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_matches_writing_layout_normal_mode_expected_false(case: Case) -> None:
    assert not await matches_writing_layout(**case.input_kwargs)


MATCHES_WRITING_LAYOUT_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000709"),
        inputs={
            "actual": (
                "Visit: Retaining Wall Site Walk\n"
                "Date Window: Friday morning\n"
                "Lead: Stormwater engineer retained on the file\n"
                "Prerequisite: Revised slope sketch completed by geotech team\n"
                "Access Note: Fence line to be opened before arrival\n"
                "Reason For Change: Tuesday slot no longer workable\n"
                "Field Constraint: Delivery lane must stay clear during inspection\n"
                "Coordination: Counsel may send alternate windows if Friday slips"
            ),
            "reference": (
                "# Friday morning retaining-wall site walk with the same engineer "
                "after the Tuesday slot failed"
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000710"),
        inputs={
            "actual": (
                "Vehicle: Orchard Truck 17\n"
                "Route: North line through pear blocks\n"
                "Modification: Refrigerated insert remains installed\n"
                "Repair: Rear liftgate rewired after relay corrosion\n"
                "Branding Issue: Replacement door decals delayed one week\n"
                "Dispatch Note: Keep truck on harvest priority list\n"
                "Service Status: Cab cleared for early-morning loading\n"
                "Parts Note: Relay housing retained after bench test"
            ),
            "reference": (
                "Orchard Truck 17 on the north pear route with its refrigerated insert "
                "still installed, the rear liftgate rewired after relay corrosion, "
                "replacement decals delayed one week, and harvest-priority dispatch "
                "status preserved for early loading."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000711"),
        inputs={
            "actual": (
                "Project: Lower Bowl Seat Replacement\n"
                "Venue: University stadium west side\n"
                "Existing Elements Retained: Numbering and aisle geometry\n"
                "Upgrade: LED aisle strips and powder-coated handrails\n"
                "Supply Issue: One mold retooled after warped cup-holder shipment\n"
                "Appearance Note: New seats installed before opener\n"
                "Inspection Item: West vomitory rail anchors rechecked after install\n"
                "Closeout Note: Remaining punch items limited to section signage"
            ),
            "reference": (
                "Lower-bowl seat replacement at the university stadium west side with "
                "numbering and aisle geometry retained, LED aisle strips and powder-"
                "coated handrails installed, one mold retooled after warped cup "
                "holders, and the new seats in place before the opener."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000712"),
        inputs={
            "actual": (
                "Record: 1912 Donation Ledger Page\n"
                "Verification: Signature matches binder copy\n"
                "Imaging Status: Scan request entered queue\n"
                "Reading Room Placement: Supervised bay only\n"
                "Paper Condition: Brittle at fold\n"
                "Optional Add-On: Shipping receipt may be retrieved with same pull\n"
                "Access Note: Keep folder off open tables\n"
                "Staff Alert: Reading-room team notified before retrieval"
            ),
            "reference": (
                "1912 donation-ledger record verified against the binder signature "
                "copy with the scan already queued, supervised-bay placement because "
                "the fold is brittle, the reading-room team notified in advance, and "
                "the shipping receipt available on the same pull."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_LAYOUT_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_matches_writing_layout_strict_mode_expected_true(case: Case) -> None:
    assert await matches_writing_layout(**case.input_kwargs)


MATCHES_WRITING_LAYOUT_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000713"),
        inputs={
            "actual": (
                "## Weekly Harbor Update\n\n"
                "Federal reviewers requested another clarification round on berth "
                "geometry and dredging access.\n\n"
                "## Neighborhood Issues\n"
                "- Truck noise\n"
                "- Light spill from nighttime pile work\n"
                "- Questions about cannery demolition\n\n"
                "## Next Steps\n"
                "Lease negotiations continue separately from the grant."
            ),
            "reference": (
                '{\n'
                '  "project": "port modernization",\n'
                '  "review_stage": "clarification round",\n'
                '  "issues": ["truck noise", "light spill", "cannery sheds"],\n'
                '  "next_step": "continue lease talks separately"\n'
                '}'
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000714"),
        inputs={
            "actual": (
                "Question | Answer\n"
                "What failed? | Basement transfer switch\n"
                "What is down? | Elevators\n"
                "What is restored? | Corridor lighting floors two through seven\n"
                "Next update? | 18:30"
            ),
            "reference": (
                "Power-loss summary: facilities traced the outage to a basement "
                "transfer-switch failure, corridor lighting came back on floors two "
                "through seven, elevators remain unavailable, and another update will "
                "be posted at 18:30."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000715"),
        inputs={
            "actual": (
                "Dear team,\n\n"
                "The ferry photos finally landed in the archive drive. I tagged the "
                "heritage-wrap weekend shots and moved the duplicate dock images into "
                "a holding folder. Please review the two frames where the livery color "
                "shifts under different light.\n\n"
                "Best,\n"
                "Maya"
            ),
            "reference": (
                "- heritage-wrap shots tagged\n"
                "- duplicate dock images moved\n"
                "- two frames need color review\n"
                "- museum volunteer logging in later"
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000716"),
        inputs={
            "actual": (
                "The investor note says the annual meeting will move online, travel "
                "remains frozen except for clinical-site visits, and one floor of the "
                "old Boston office may be subleased after chemistry work shifted south. "
                "Another paragraph says conference abstracts are under preparation."
            ),
            "reference": (
                "1. Annual meeting goes online\n"
                "2. Travel freeze remains in effect\n"
                "3. Boston office floor may be subleased\n"
                "4. Conference abstracts are in preparation"
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*MATCHES_WRITING_LAYOUT_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_matches_writing_layout_strict_mode_expected_false(case: Case) -> None:
    assert not await matches_writing_layout(**case.input_kwargs)
