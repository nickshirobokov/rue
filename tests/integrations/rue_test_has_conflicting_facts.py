from uuid import UUID

import rue
from rue import Case
from rue.predicates import has_conflicting_facts


HAS_CONFLICTING_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000101"),
        sut_input_values={
            "actual": (
                "The airport authority circulated a renovation brief before the March "
                "finance committee meeting because airlines were arguing over gate "
                "assignments, baggage conveyor downtime, and whether customs "
                "inspection should stay in the east concourse during construction. The "
                "packet explains that the terminal built in the late 1980s still uses "
                "an undersized outbound belt system, has restrooms that miss current "
                "accessibility clearances, and relies on a temporary corridor for "
                "arriving international passengers whenever two wide-body flights "
                "overlap. It also summarizes comments from union ramp supervisors, the "
                "retail tenant association, and the county fire marshal, all of whom "
                "asked for a schedule that would avoid the summer holiday peak.\n\n"
                "The operations section says Gate C will close for six weeks beginning "
                "on August 12, the customs hall rebuild has been deferred until spring "
                "2027, and international arrivals will keep using the temporary "
                "east-corridor route until the conveyor replacement is finished.\n\n"
                "The closing pages of the brief cover items that are not in dispute: "
                "the airport will keep the south security checkpoint open throughout "
                "the project, snow-removal equipment will remain staged near Hangar "
                "Three, and the airport hotel shuttle contract will be rebid in "
                "September regardless of the terminal work. A short appendix also "
                "notes that the public art wall from the old commuter wing will be "
                "cataloged before demolition, because neighborhood groups want several "
                "ceramic panels moved into the future arrivals hall instead of sent to "
                "storage."
            ),
            "reference": (
                "The airport authority circulated a renovation brief before the March "
                "finance committee meeting because airlines were arguing over gate "
                "assignments, baggage conveyor downtime, and whether customs "
                "inspection should stay in the east concourse during construction. The "
                "packet explains that the terminal built in the late 1980s still uses "
                "an undersized outbound belt system, has restrooms that miss current "
                "accessibility clearances, and relies on a temporary corridor for "
                "arriving international passengers whenever two wide-body flights "
                "overlap. It also summarizes comments from union ramp supervisors, the "
                "retail tenant association, and the county fire marshal, all of whom "
                "asked for a schedule that would avoid the summer holiday peak.\n\n"
                "The operations section says Gate C will remain open through the "
                "holiday schedule, the customs hall rebuild will begin this October, "
                "and international arrivals will be rerouted to the south concourse as "
                "soon as demolition fencing goes up.\n\n"
                "The closing pages of the brief cover items that are not in dispute: "
                "the airport will keep the south security checkpoint open throughout "
                "the project, snow-removal equipment will remain staged near Hangar "
                "Three, and the airport hotel shuttle contract will be rebid in "
                "September regardless of the terminal work. A short appendix also "
                "notes that the public art wall from the old commuter wing will be "
                "cataloged before demolition, because neighborhood groups want several "
                "ceramic panels moved into the future arrivals hall instead of sent to "
                "storage."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000102"),
        sut_input_values={
            "actual": (
                "Public Works sent council members a weekend bridge status packet "
                "after a freight truck strike damaged two gusset plates and forced "
                "buses onto a detour through the warehouse district. The report walks "
                "through the temporary shoring plan, the sequence of ultrasonic "
                "inspections, and the political pressure on the mayor's office from "
                "restaurant owners who lost lunch traffic while the crossing stayed "
                "closed. Engineers explain that the bridge deck itself never slipped "
                "out of alignment, but the city could not reopen the route until the "
                "contractor submitted weld certifications and the state inspector "
                "signed the revised load limit. Transit dispatch notes in the appendix "
                "show how the detour added fourteen minutes to each loop during the "
                "first business day.\n\n"
                "According to the status packet, engineers signed the final load test "
                "before dawn on Monday, buses returned to their usual route by 11:30 "
                "that morning, and the city reopened all four traffic lanes before the "
                "lunch rush.\n\n"
                "The final section discusses the less dramatic follow-up items: crews "
                "still need to replace damaged barrier posts, repaint lane arrows at "
                "both approaches, and reset the variable-message signs that warned "
                "drivers about the closure. The packet also records merchant requests "
                "for temporary parking validation and the school district's complaint "
                "that two buses missed the first morning bell because they were routed "
                "around the riverfront. None of those side issues changes the central "
                "timeline the city used to brief elected officials."
            ),
            "reference": (
                "Public Works sent council members a weekend bridge status packet "
                "after a freight truck strike damaged two gusset plates and forced "
                "buses onto a detour through the warehouse district. The report walks "
                "through the temporary shoring plan, the sequence of ultrasonic "
                "inspections, and the political pressure on the mayor's office from "
                "restaurant owners who lost lunch traffic while the crossing stayed "
                "closed. Engineers explain that the bridge deck itself never slipped "
                "out of alignment, but the city could not reopen the route until the "
                "contractor submitted weld certifications and the state inspector "
                "signed the revised load limit. Transit dispatch notes in the appendix "
                "show how the detour added fourteen minutes to each loop during the "
                "first business day.\n\n"
                "According to the status packet, engineers withheld approval all day "
                "Monday, buses stayed on detour until Tuesday afternoon, and the city "
                "kept the bridge fully closed to general traffic until the next day.\n\n"
                "The final section discusses the less dramatic follow-up items: crews "
                "still need to replace damaged barrier posts, repaint lane arrows at "
                "both approaches, and reset the variable-message signs that warned "
                "drivers about the closure. The packet also records merchant requests "
                "for temporary parking validation and the school district's complaint "
                "that two buses missed the first morning bell because they were routed "
                "around the riverfront. None of those side issues changes the central "
                "timeline the city used to brief elected officials."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000103"),
        sut_input_values={
            "actual": (
                "The biotechnology company drafted a long investor update after "
                "completing the second interim look at its respiratory-drug trial. The "
                "letter explains the study population, reminds readers that the trial "
                "enrolled patients across forty community pulmonology clinics rather "
                "than elite academic centers, and repeats that the primary endpoint "
                "tracks severe exacerbations over a full winter season. Management "
                "included extra detail because analysts kept confusing the current "
                "inhaled therapy program with an older monoclonal antibody project "
                "that was sold two years ago. The update also describes manufacturing "
                "work at the New Mexico fill-finish plant, which has to validate a new "
                "canister valve before the company can ship commercial batches if "
                "regulators approve the drug.\n\n"
                "The update says the interim analysis found enough benefit in adults "
                "with severe asthma that management now plans to file for approval in "
                "that adult population before year-end, while pediatric work remains "
                "exploratory and outside the current submission.\n\n"
                "The rest of the document focuses on investor relations housekeeping. "
                "Executives say the annual meeting will move online because the audit "
                "committee chair is recovering from surgery, employee travel remains "
                "frozen except for clinical-site visits, and the company still expects "
                "to sublease one floor of its old Boston office after most chemistry "
                "work shifted to North Carolina. An appendix from the medical affairs "
                "team lists conference abstracts under preparation, but those poster "
                "plans do not change the core regulatory facts investors need from the "
                "trial update."
            ),
            "reference": (
                "The biotechnology company drafted a long investor update after "
                "completing the second interim look at its respiratory-drug trial. The "
                "letter explains the study population, reminds readers that the trial "
                "enrolled patients across forty community pulmonology clinics rather "
                "than elite academic centers, and repeats that the primary endpoint "
                "tracks severe exacerbations over a full winter season. Management "
                "included extra detail because analysts kept confusing the current "
                "inhaled therapy program with an older monoclonal antibody project "
                "that was sold two years ago. The update also describes manufacturing "
                "work at the New Mexico fill-finish plant, which has to validate a new "
                "canister valve before the company can ship commercial batches if "
                "regulators approve the drug.\n\n"
                "The update says the company will pursue an adolescent-only filing "
                "because the adult cohort failed to separate from placebo, and "
                "executives describe the adult program as unlikely to move forward "
                "without a new Phase Three study.\n\n"
                "The rest of the document focuses on investor relations housekeeping. "
                "Executives say the annual meeting will move online because the audit "
                "committee chair is recovering from surgery, employee travel remains "
                "frozen except for clinical-site visits, and the company still expects "
                "to sublease one floor of its old Boston office after most chemistry "
                "work shifted to North Carolina. An appendix from the medical affairs "
                "team lists conference abstracts under preparation, but those poster "
                "plans do not change the core regulatory facts investors need from the "
                "trial update."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000104"),
        sut_input_values={
            "actual": (
                "The housing authority board packet for April combines a rent "
                "recommendation memo, a capital-maintenance forecast, and a "
                "resident-services update because commissioners wanted a single "
                "document before voting on next year's budget. Staff describe elevator "
                "outages in the oldest towers, explain why insurance premiums rose "
                "after two kitchen fires, and note that the waiting list reopened for "
                "the first time in eighteen months after three renovated buildings "
                "passed inspection. Tenant leaders submitted letters asking the board "
                "to phase in any increases slowly and to publish clearer notices in "
                "Spanish, Vietnamese, and Somali. The packet also contains a legal "
                "summary of the deed restrictions on the senior campus, which limit "
                "how aggressively the authority can reshuffle vacant units across "
                "funding programs.\n\n"
                "The recommendation memo calls for a six percent increase on "
                "market-rate apartments effective July 1, while senior units remain "
                "frozen for the rest of the calendar year because of the deed "
                "restrictions on the older campus.\n\n"
                "Background tables at the end of the packet list boiler replacement "
                "dates, sidewalk repair costs, and the draw schedule for a state "
                "weatherization grant. A staff note says case managers are seeing more "
                "requests for transit vouchers from residents who now travel to a "
                "suburban dialysis clinic, and procurement officers flag that one "
                "landscaping contract will expire midseason. Those details provide "
                "context for the board's vote, but they do not alter the core policy "
                "recommendation laid out in the main memorandum."
            ),
            "reference": (
                "The housing authority board packet for April combines a rent "
                "recommendation memo, a capital-maintenance forecast, and a "
                "resident-services update because commissioners wanted a single "
                "document before voting on next year's budget. Staff describe elevator "
                "outages in the oldest towers, explain why insurance premiums rose "
                "after two kitchen fires, and note that the waiting list reopened for "
                "the first time in eighteen months after three renovated buildings "
                "passed inspection. Tenant leaders submitted letters asking the board "
                "to phase in any increases slowly and to publish clearer notices in "
                "Spanish, Vietnamese, and Somali. The packet also contains a legal "
                "summary of the deed restrictions on the senior campus, which limit "
                "how aggressively the authority can reshuffle vacant units across "
                "funding programs.\n\n"
                "The recommendation memo calls for a full rent freeze across every "
                "property through December 31, including market-rate apartments, "
                "senior units, and the mixed-finance redevelopment sites that reopened "
                "this spring.\n\n"
                "Background tables at the end of the packet list boiler replacement "
                "dates, sidewalk repair costs, and the draw schedule for a state "
                "weatherization grant. A staff note says case managers are seeing more "
                "requests for transit vouchers from residents who now travel to a "
                "suburban dialysis clinic, and procurement officers flag that one "
                "landscaping contract will expire midseason. Those details provide "
                "context for the board's vote, but they do not alter the core policy "
                "recommendation laid out in the main memorandum."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_CONFLICTING_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_conflicting_facts_normal_mode_expected_true(case: Case) -> None:
    assert await has_conflicting_facts(**case.sut_input_values)


HAS_CONFLICTING_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000105"),
        sut_input_values={
            "actual": (
                "The rail maintenance manual for the harbor spur includes a "
                "troubleshooting note about the old signal relay cabinet at Junction "
                "Seven because crews kept reporting inconsistent lamp colors during "
                "night inspections. The note reminds technicians that the panel uses "
                "different lenses to communicate state changes: one appearance during "
                "boot-up, another while the circuit is actively charging, and a third "
                "when the relay trips into fault mode. Supervisors added the note "
                "after a trainee escalated what looked like a contradiction between "
                "photographs taken at two different moments in the reset sequence. The "
                "manual explicitly says the unit's faceplate, cable routing, and "
                "housing serial number do not change; only the illuminated indicator "
                "shifts as the system moves through its expected operating states.\n\n"
                "The note says the indicator looked amber at 05:48 while the cabinet "
                "was booting after a power cut and before the charging circuit had "
                "latched.\n\n"
                "The appendix walks through the rest of the cabinet inspection: "
                "tighten the terminal screws, verify the gasket is seated, wipe "
                "condensation from the inner shield, and confirm that the event logger "
                "stamped the reset in the maintenance database before the crew leaves "
                "the site. A final reminder tells supervisors not to replace the "
                "assembly simply because two photos show different colors if the "
                "timestamps prove the cabinet was moving from one normal state to "
                "another."
            ),
            "reference": (
                "The rail maintenance manual for the harbor spur includes a "
                "troubleshooting note about the old signal relay cabinet at Junction "
                "Seven because crews kept reporting inconsistent lamp colors during "
                "night inspections. The note reminds technicians that the panel uses "
                "different lenses to communicate state changes: one appearance during "
                "boot-up, another while the circuit is actively charging, and a third "
                "when the relay trips into fault mode. Supervisors added the note "
                "after a trainee escalated what looked like a contradiction between "
                "photographs taken at two different moments in the reset sequence. The "
                "manual explicitly says the unit's faceplate, cable routing, and "
                "housing serial number do not change; only the illuminated indicator "
                "shifts as the system moves through its expected operating states.\n\n"
                "The note says the same indicator looked green at 05:51 once the "
                "charging circuit had latched and the cabinet had moved into its "
                "normal energized state.\n\n"
                "The appendix walks through the rest of the cabinet inspection: "
                "tighten the terminal screws, verify the gasket is seated, wipe "
                "condensation from the inner shield, and confirm that the event logger "
                "stamped the reset in the maintenance database before the crew leaves "
                "the site. A final reminder tells supervisors not to replace the "
                "assembly simply because two photos show different colors if the "
                "timestamps prove the cabinet was moving from one normal state to "
                "another."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000106"),
        sut_input_values={
            "actual": (
                "The repertory theater's wardrobe report explains why the lead actor's "
                "parade coat appears to have different colors across rehearsal photos, "
                "donor previews, and the final dress run archived for the streaming "
                "release. Costumers note that the coat was built from an iridescent "
                "fabric with a dark base weave and a reflective overprint, so the "
                "garment reads one way under warm tungsten lamps, another under the "
                "cool LED wash used for camera rehearsals, and another again under "
                "lobby lighting when patrons take selfies during backstage tours. The "
                "report was prepared because a sponsor thought the theater had "
                "replaced the coat after the first preview, when in fact the same "
                "garment was used throughout the production and only the lighting "
                "design changed.\n\n"
                "The report says the parade coat read deep blue under the cool LED "
                "wash used for the camera rehearsal recorded on Thursday night.\n\n"
                "The wardrobe team also documents less dramatic continuity points. "
                "Buttons were reattached after a dance lift snagged the cuff, a new "
                "sweat guard was stitched into the collar before the Saturday matinee, "
                "and the hem was let down by half an inch after the actor switched "
                "boots. Those maintenance details matter to the costume archive, but "
                "they do not alter the report's basic explanation that the same coat "
                "can honestly be described with different color words in different "
                "lighting conditions."
            ),
            "reference": (
                "The repertory theater's wardrobe report explains why the lead actor's "
                "parade coat appears to have different colors across rehearsal photos, "
                "donor previews, and the final dress run archived for the streaming "
                "release. Costumers note that the coat was built from an iridescent "
                "fabric with a dark base weave and a reflective overprint, so the "
                "garment reads one way under warm tungsten lamps, another under the "
                "cool LED wash used for camera rehearsals, and another again under "
                "lobby lighting when patrons take selfies during backstage tours. The "
                "report was prepared because a sponsor thought the theater had "
                "replaced the coat after the first preview, when in fact the same "
                "garment was used throughout the production and only the lighting "
                "design changed.\n\n"
                "The report says the same parade coat read emerald green under the "
                "warm tungsten front light used during the donor preview on Wednesday "
                "evening.\n\n"
                "The wardrobe team also documents less dramatic continuity points. "
                "Buttons were reattached after a dance lift snagged the cuff, a new "
                "sweat guard was stitched into the collar before the Saturday matinee, "
                "and the hem was let down by half an inch after the actor switched "
                "boots. Those maintenance details matter to the costume archive, but "
                "they do not alter the report's basic explanation that the same coat "
                "can honestly be described with different color words in different "
                "lighting conditions."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000107"),
        sut_input_values={
            "actual": (
                "The commuter rail operator sent photographers and museum volunteers a "
                "note about Car 412 because the train spent one week carrying a "
                "temporary heritage wrap while the permanent fleet livery team waited "
                "for replacement decals. The note clarifies that the stainless body "
                "shell did not change ownership or route assignment, but its exterior "
                "appearance legitimately differed between the depot rollout ceremony, "
                "the regular weekday service photos, and the maintenance-bay images "
                "taken after the wrap was peeled back. Archive staff asked for the "
                "note because captions from local newspapers were already using "
                "inconsistent color descriptions, and the transit museum wanted to "
                "avoid rejecting historically accurate images simply because the car "
                "looked different across events.\n\n"
                "The archive note says Car 412 appeared cream and burgundy during the "
                "heritage-wrap ceremony held outside the depot on June 3.\n\n"
                "Another section covers operational trivia that is not central to the "
                "paint question. Car 412 still used the same traction motors after the "
                "wrap period, it kept the same wheelchair ramp module, and it remained "
                "assigned to the north line except for one weekend substitution on the "
                "airport branch. The point of the note is narrower: a single railcar "
                "can be described with different colors when the timestamps correspond "
                "to different livery phases rather than a factual contradiction."
            ),
            "reference": (
                "The commuter rail operator sent photographers and museum volunteers a "
                "note about Car 412 because the train spent one week carrying a "
                "temporary heritage wrap while the permanent fleet livery team waited "
                "for replacement decals. The note clarifies that the stainless body "
                "shell did not change ownership or route assignment, but its exterior "
                "appearance legitimately differed between the depot rollout ceremony, "
                "the regular weekday service photos, and the maintenance-bay images "
                "taken after the wrap was peeled back. Archive staff asked for the "
                "note because captions from local newspapers were already using "
                "inconsistent color descriptions, and the transit museum wanted to "
                "avoid rejecting historically accurate images simply because the car "
                "looked different across events.\n\n"
                "The archive note says Car 412 appeared stainless silver with a navy "
                "band after the temporary wrap was removed before weekday service "
                "resumed on June 10.\n\n"
                "Another section covers operational trivia that is not central to the "
                "paint question. Car 412 still used the same traction motors after the "
                "wrap period, it kept the same wheelchair ramp module, and it remained "
                "assigned to the north line except for one weekend substitution on the "
                "airport branch. The point of the note is narrower: a single railcar "
                "can be described with different colors when the timestamps correspond "
                "to different livery phases rather than a factual contradiction."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000108"),
        sut_input_values={
            "actual": (
                "The coast guard station's buoy handbook contains a short briefing on "
                "the outer harbor beacon because apprentice coxswains kept submitting "
                "discrepancy reports after training watches logged different lamp "
                "colors for the same device. The handbook explains that the beacon "
                "uses a programmable LED array which shows one color in steady "
                "navigation mode, another during battery diagnostics, and a third when "
                "the maintenance crew switches it into identification mode while "
                "approaching by launch. All three appearances can be correct, and the "
                "station commander included annotated photographs to stop crews from "
                "treating every color change as proof that the buoy had drifted or "
                "been replaced without notice.\n\n"
                "The handbook says the outer beacon flashes red while the maintenance "
                "launch has it in identification mode during close approach checks.\n\n"
                "Supplemental notes address maintenance chores around the beacon: "
                "scrape marine growth from the ladder rungs, verify the solar panel "
                "hinges still lock, and clear nesting material from the vent cap "
                "before sealing the battery compartment. A final caution tells crews "
                "to log the operating mode alongside the color observed, because a "
                "bare color report without that mode information is too incomplete to "
                "establish a contradiction on its own."
            ),
            "reference": (
                "The coast guard station's buoy handbook contains a short briefing on "
                "the outer harbor beacon because apprentice coxswains kept submitting "
                "discrepancy reports after training watches logged different lamp "
                "colors for the same device. The handbook explains that the beacon "
                "uses a programmable LED array which shows one color in steady "
                "navigation mode, another during battery diagnostics, and a third when "
                "the maintenance crew switches it into identification mode while "
                "approaching by launch. All three appearances can be correct, and the "
                "station commander included annotated photographs to stop crews from "
                "treating every color change as proof that the buoy had drifted or "
                "been replaced without notice.\n\n"
                "The handbook says the outer beacon shows steady green while it is in "
                "normal navigation mode after crews leave the station and the "
                "identification setting is switched off.\n\n"
                "Supplemental notes address maintenance chores around the beacon: "
                "scrape marine growth from the ladder rungs, verify the solar panel "
                "hinges still lock, and clear nesting material from the vent cap "
                "before sealing the battery compartment. A final caution tells crews "
                "to log the operating mode alongside the color observed, because a "
                "bare color report without that mode information is too incomplete to "
                "establish a contradiction on its own."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_CONFLICTING_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_conflicting_facts_normal_mode_expected_false(case: Case) -> None:
    assert not await has_conflicting_facts(**case.sut_input_values)


HAS_CONFLICTING_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000109"),
        sut_input_values={
            "actual": (
                "The museum foundation prepared a restoration memorandum for donors "
                "after water infiltrated the north gallery during January storms and "
                "stained the plaster over several nineteenth-century seascapes. The "
                "memo summarizes the roofer's findings, the conservator's moisture "
                "readings, and the legal review of the original construction contract "
                "from 1997, which turned out to exclude damage caused by deferred "
                "maintenance. Trustees were especially interested in how the project "
                "would affect the summer exhibition schedule because the maritime art "
                "show already has loans coming from Rotterdam, Boston, and Halifax. "
                "The finance committee also asked for a plain-language explanation of "
                "which costs qualify for the city's heritage-preservation rebate and "
                "which costs must be paid from unrestricted operating reserves.\n\n"
                "The board memo says the preservation rebate will cover forty percent "
                "of the roof project, the museum will replace the entire copper skin "
                "over the north gallery this summer, and the maritime exhibition will "
                "open on schedule after a brief one-week install delay.\n\n"
                "Later paragraphs cover the museum's contingency planning. Staff will "
                "shift school tours into the sculpture court if the western stairwell "
                "has to close, the café will use a reduced menu while dust barriers "
                "are installed, and the gift shop plans to postpone its inventory "
                "audit until the roof contractors have left the loading dock. An "
                "attachment from the registrar lists works that must stay in "
                "climate-controlled crates during the loudest phase of the project, "
                "but those handling details are separate from the core funding and "
                "scope decisions the board is trying to understand."
            ),
            "reference": (
                "The museum foundation prepared a restoration memorandum for donors "
                "after water infiltrated the north gallery during January storms and "
                "stained the plaster over several nineteenth-century seascapes. The "
                "memo summarizes the roofer's findings, the conservator's moisture "
                "readings, and the legal review of the original construction contract "
                "from 1997, which turned out to exclude damage caused by deferred "
                "maintenance. Trustees were especially interested in how the project "
                "would affect the summer exhibition schedule because the maritime art "
                "show already has loans coming from Rotterdam, Boston, and Halifax. "
                "The finance committee also asked for a plain-language explanation of "
                "which costs qualify for the city's heritage-preservation rebate and "
                "which costs must be paid from unrestricted operating reserves.\n\n"
                "The board memo says the preservation rebate was denied, only patch "
                "repairs will be performed on the north roof before winter, and the "
                "maritime exhibition must be postponed because the gallery cannot "
                "reopen in time for incoming loans.\n\n"
                "Later paragraphs cover the museum's contingency planning. Staff will "
                "shift school tours into the sculpture court if the western stairwell "
                "has to close, the café will use a reduced menu while dust barriers "
                "are installed, and the gift shop plans to postpone its inventory "
                "audit until the roof contractors have left the loading dock. An "
                "attachment from the registrar lists works that must stay in "
                "climate-controlled crates during the loudest phase of the project, "
                "but those handling details are separate from the core funding and "
                "scope decisions the board is trying to understand."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000110"),
        sut_input_values={
            "actual": (
                "The harbor authority issued a grant briefing after federal reviewers "
                "asked for another clarification round on the port modernization "
                "package. The document explains that exporters want deeper berths for "
                "refrigerated cargo, tug operators want the turning basin widened "
                "before winter storms return, and the nearby fishing fleet wants "
                "written guarantees that bait trucks will keep access to the ice plant "
                "during dredging. A policy appendix compares the project with earlier "
                "shoreline repairs that used state resilience money rather than "
                "freight grants. The briefing also reproduces questions from "
                "neighborhood residents who are worried about truck noise, light spill "
                "from nighttime pile work, and what happens to the derelict cannery "
                "sheds sitting on the western edge of the site.\n\n"
                "The grant briefing says federal funds can be used for dredging the "
                "turning basin and demolishing the derelict cannery sheds, while "
                "refrigerated cargo berths will be prioritized in the first "
                "construction package.\n\n"
                "In a section on implementation, the authority says customs staffing "
                "is outside the grant, lease negotiations with the cold-storage tenant "
                "continue on a separate track, and none of the current crane operators "
                "will lose seniority if the berth redesign goes forward. The final "
                "page lists background items such as sediment sampling dates, vessel "
                "counts, and a reminder that the annual harbor festival will be moved "
                "upriver if the demolition permit is still active in August. Those "
                "supporting details matter politically, but they are not the heart of "
                "the grant terms under debate."
            ),
            "reference": (
                "The harbor authority issued a grant briefing after federal reviewers "
                "asked for another clarification round on the port modernization "
                "package. The document explains that exporters want deeper berths for "
                "refrigerated cargo, tug operators want the turning basin widened "
                "before winter storms return, and the nearby fishing fleet wants "
                "written guarantees that bait trucks will keep access to the ice plant "
                "during dredging. A policy appendix compares the project with earlier "
                "shoreline repairs that used state resilience money rather than "
                "freight grants. The briefing also reproduces questions from "
                "neighborhood residents who are worried about truck noise, light spill "
                "from nighttime pile work, and what happens to the derelict cannery "
                "sheds sitting on the western edge of the site.\n\n"
                "The grant briefing says federal funds cannot be used for dredging or "
                "demolition at the cannery edge, and the first package is limited to "
                "upland roadwork with berth expansion pushed into a later phase.\n\n"
                "In a section on implementation, the authority says customs staffing "
                "is outside the grant, lease negotiations with the cold-storage tenant "
                "continue on a separate track, and none of the current crane operators "
                "will lose seniority if the berth redesign goes forward. The final "
                "page lists background items such as sediment sampling dates, vessel "
                "counts, and a reminder that the annual harbor festival will be moved "
                "upriver if the demolition permit is still active in August. Those "
                "supporting details matter politically, but they are not the heart of "
                "the grant terms under debate."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000111"),
        sut_input_values={
            "actual": (
                "A regional history archive assembled a relocation brief after its "
                "volunteer board agreed to leave a crumbling lodge on the edge of the "
                "fairgrounds and move collections into a renovated streetcar depot "
                "downtown. The brief walks through humidity readings in the map room, "
                "explains how the city offered to absorb utility bills in exchange for "
                "public programming, and recounts months of negotiation with "
                "descendants of the archive's founder who were worried that family "
                "papers would lose dedicated shelf space after the move. Curators "
                "wrote the document in unusually plain language because half the "
                "archive's donors are retirees who do not read grant paperwork "
                "comfortably and wanted a direct account of who will pay for "
                "elevators, climate control, and security.\n\n"
                "The relocation brief says the city accepted title to the archive "
                "building, will pay the depot utilities for at least five years, and "
                "has agreed to appoint the new director once the volunteer board "
                "dissolves.\n\n"
                "The annexes cover practical matters such as volunteer parking, "
                "delivery access for oversize map cases, and whether the research desk "
                "can stay open during the week the freight elevator is inspected. "
                "Another appendix inventories the building materials found behind the "
                "depot's walls after plaster came down and documents a side agreement "
                "allowing the transit museum to store spare display rails in the "
                "basement until its own warehouse lease is renewed. Those logistics "
                "are useful, but they are separate from the archive's legal status and "
                "site description at issue in the relocation debate."
            ),
            "reference": (
                "A regional history archive assembled a relocation brief after its "
                "volunteer board agreed to leave a crumbling lodge on the edge of the "
                "fairgrounds and move collections into a renovated streetcar depot "
                "downtown. The brief walks through humidity readings in the map room, "
                "explains how the city offered to absorb utility bills in exchange for "
                "public programming, and recounts months of negotiation with "
                "descendants of the archive's founder who were worried that family "
                "papers would lose dedicated shelf space after the move. Curators "
                "wrote the document in unusually plain language because half the "
                "archive's donors are retirees who do not read grant paperwork "
                "comfortably and wanted a direct account of who will pay for "
                "elevators, climate control, and security.\n\n"
                "The relocation brief says the archive will remain an entirely "
                "independent tenant, the city will not assume utility costs, and the "
                "volunteer board will continue appointing its own director after the "
                "move.\n\n"
                "The annexes cover practical matters such as volunteer parking, "
                "delivery access for oversize map cases, and whether the research desk "
                "can stay open during the week the freight elevator is inspected. "
                "Another appendix inventories the building materials found behind the "
                "depot's walls after plaster came down and documents a side agreement "
                "allowing the transit museum to store spare display rails in the "
                "basement until its own warehouse lease is renewed. Those logistics "
                "are useful, but they are separate from the archive's legal status and "
                "site description at issue in the relocation debate."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000112"),
        sut_input_values={
            "actual": (
                "The governor's office commissioned a strategy memo on semiconductor "
                "expansion because two equipment suppliers are considering sites near "
                "the inland airport and lawmakers want a clear picture of subsidy "
                "exposure before the next budget session. The memo compares power "
                "demand across fabrication steps, outlines the mineral-processing "
                "bottlenecks for photoresist chemicals and specialty gases, and "
                "summarizes federal export-control constraints that could limit which "
                "tools are allowed on the proposed campus. Labor agencies contributed "
                "a section on the shortage of industrial electricians and ultra-pure "
                "water technicians, while the commerce department added interviews "
                "with community colleges trying to design certificate programs fast "
                "enough to matter before site work starts.\n\n"
                "The strategy memo treats export controls as a major constraint on "
                "which tools can be installed, says the state would need a large "
                "subsidy package to compete, and warns that the labor shortage among "
                "industrial electricians is a serious risk to the project timeline.\n\n"
                "Near the end, the memo shifts to politics. Rural legislators want "
                "assurances that road upgrades serving the plant will not crowd out "
                "bridge repairs in their districts, environmental groups demand a "
                "public accounting of solvent recovery plans, and the airport "
                "authority is lobbying for cargo apron improvements so replacement "
                "parts do not have to truck in from another state. Those pressures "
                "shape implementation, but they do not alter the memo's central "
                "description of ownership, trade exposure, and industrial-policy "
                "choices."
            ),
            "reference": (
                "The governor's office commissioned a strategy memo on semiconductor "
                "expansion because two equipment suppliers are considering sites near "
                "the inland airport and lawmakers want a clear picture of subsidy "
                "exposure before the next budget session. The memo compares power "
                "demand across fabrication steps, outlines the mineral-processing "
                "bottlenecks for photoresist chemicals and specialty gases, and "
                "summarizes federal export-control constraints that could limit which "
                "tools are allowed on the proposed campus. Labor agencies contributed "
                "a section on the shortage of industrial electricians and ultra-pure "
                "water technicians, while the commerce department added interviews "
                "with community colleges trying to design certificate programs fast "
                "enough to matter before site work starts.\n\n"
                "The strategy memo says export controls are largely irrelevant to the "
                "proposed tool set, rejects the need for sizable subsidies, and "
                "describes the skilled-labor pipeline as already adequate for "
                "immediate build-out.\n\n"
                "Near the end, the memo shifts to politics. Rural legislators want "
                "assurances that road upgrades serving the plant will not crowd out "
                "bridge repairs in their districts, environmental groups demand a "
                "public accounting of solvent recovery plans, and the airport "
                "authority is lobbying for cargo apron improvements so replacement "
                "parts do not have to truck in from another state. Those pressures "
                "shape implementation, but they do not alter the memo's central "
                "description of ownership, trade exposure, and industrial-policy "
                "choices."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_CONFLICTING_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_conflicting_facts_strict_mode_expected_true(case: Case) -> None:
    assert await has_conflicting_facts(**case.sut_input_values)


HAS_CONFLICTING_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000113"),
        sut_input_values={
            "actual": (
                "The rail maintenance manual for the harbor spur includes a "
                "troubleshooting note about the old signal relay cabinet at Junction "
                "Seven because crews kept reporting inconsistent lamp colors during "
                "night inspections. The note reminds technicians that the panel uses "
                "different lenses to communicate state changes: one appearance during "
                "boot-up, another while the circuit is actively charging, and a third "
                "when the relay trips into fault mode. Supervisors added the note "
                "after a trainee escalated what looked like a contradiction between "
                "photographs taken at two different moments in the reset sequence. The "
                "manual explicitly says the unit's faceplate, cable routing, and "
                "housing serial number do not change; only the illuminated indicator "
                "shifts as the system moves through its expected operating states.\n\n"
                "The maintenance note says the cabinet showed blue during the "
                "overnight diagnostics sequence after crews manually forced a battery "
                "check.\n\n"
                "The appendix walks through the rest of the cabinet inspection: "
                "tighten the terminal screws, verify the gasket is seated, wipe "
                "condensation from the inner shield, and confirm that the event logger "
                "stamped the reset in the maintenance database before the crew leaves "
                "the site. A final reminder tells supervisors not to replace the "
                "assembly simply because two photos show different colors if the "
                "timestamps prove the cabinet was moving from one normal state to "
                "another."
            ),
            "reference": (
                "The rail maintenance manual for the harbor spur includes a "
                "troubleshooting note about the old signal relay cabinet at Junction "
                "Seven because crews kept reporting inconsistent lamp colors during "
                "night inspections. The note reminds technicians that the panel uses "
                "different lenses to communicate state changes: one appearance during "
                "boot-up, another while the circuit is actively charging, and a third "
                "when the relay trips into fault mode. Supervisors added the note "
                "after a trainee escalated what looked like a contradiction between "
                "photographs taken at two different moments in the reset sequence. The "
                "manual explicitly says the unit's faceplate, cable routing, and "
                "housing serial number do not change; only the illuminated indicator "
                "shifts as the system moves through its expected operating states.\n\n"
                "The maintenance note says the cabinet showed amber during the "
                "subsequent reboot cycle after technicians exited diagnostics and "
                "restarted the relay.\n\n"
                "The appendix walks through the rest of the cabinet inspection: "
                "tighten the terminal screws, verify the gasket is seated, wipe "
                "condensation from the inner shield, and confirm that the event logger "
                "stamped the reset in the maintenance database before the crew leaves "
                "the site. A final reminder tells supervisors not to replace the "
                "assembly simply because two photos show different colors if the "
                "timestamps prove the cabinet was moving from one normal state to "
                "another."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000114"),
        sut_input_values={
            "actual": (
                "The repertory theater's wardrobe report explains why the lead actor's "
                "parade coat appears to have different colors across rehearsal photos, "
                "donor previews, and the final dress run archived for the streaming "
                "release. Costumers note that the coat was built from an iridescent "
                "fabric with a dark base weave and a reflective overprint, so the "
                "garment reads one way under warm tungsten lamps, another under the "
                "cool LED wash used for camera rehearsals, and another again under "
                "lobby lighting when patrons take selfies during backstage tours. The "
                "report was prepared because a sponsor thought the theater had "
                "replaced the coat after the first preview, when in fact the same "
                "garment was used throughout the production and only the lighting "
                "design changed.\n\n"
                "The continuity record says the coat looked black from the balcony "
                "during the low-light funeral scene in Act Two.\n\n"
                "The wardrobe team also documents less dramatic continuity points. "
                "Buttons were reattached after a dance lift snagged the cuff, a new "
                "sweat guard was stitched into the collar before the Saturday matinee, "
                "and the hem was let down by half an inch after the actor switched "
                "boots. Those maintenance details matter to the costume archive, but "
                "they do not alter the report's basic explanation that the same coat "
                "can honestly be described with different color words in different "
                "lighting conditions."
            ),
            "reference": (
                "The repertory theater's wardrobe report explains why the lead actor's "
                "parade coat appears to have different colors across rehearsal photos, "
                "donor previews, and the final dress run archived for the streaming "
                "release. Costumers note that the coat was built from an iridescent "
                "fabric with a dark base weave and a reflective overprint, so the "
                "garment reads one way under warm tungsten lamps, another under the "
                "cool LED wash used for camera rehearsals, and another again under "
                "lobby lighting when patrons take selfies during backstage tours. The "
                "report was prepared because a sponsor thought the theater had "
                "replaced the coat after the first preview, when in fact the same "
                "garment was used throughout the production and only the lighting "
                "design changed.\n\n"
                "The continuity record says the same coat looked midnight purple under "
                "the backstage fluorescents when dressers photographed repairs during "
                "intermission.\n\n"
                "The wardrobe team also documents less dramatic continuity points. "
                "Buttons were reattached after a dance lift snagged the cuff, a new "
                "sweat guard was stitched into the collar before the Saturday matinee, "
                "and the hem was let down by half an inch after the actor switched "
                "boots. Those maintenance details matter to the costume archive, but "
                "they do not alter the report's basic explanation that the same coat "
                "can honestly be described with different color words in different "
                "lighting conditions."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000115"),
        sut_input_values={
            "actual": (
                "The commuter rail operator sent photographers and museum volunteers a "
                "note about Car 412 because the train spent one week carrying a "
                "temporary heritage wrap while the permanent fleet livery team waited "
                "for replacement decals. The note clarifies that the stainless body "
                "shell did not change ownership or route assignment, but its exterior "
                "appearance legitimately differed between the depot rollout ceremony, "
                "the regular weekday service photos, and the maintenance-bay images "
                "taken after the wrap was peeled back. Archive staff asked for the "
                "note because captions from local newspapers were already using "
                "inconsistent color descriptions, and the transit museum wanted to "
                "avoid rejecting historically accurate images simply because the car "
                "looked different across events.\n\n"
                "The museum note says Car 412 appeared orange and cream during the "
                "three-day heritage festival before the commemorative vinyl was "
                "removed.\n\n"
                "Another section covers operational trivia that is not central to the "
                "paint question. Car 412 still used the same traction motors after the "
                "wrap period, it kept the same wheelchair ramp module, and it remained "
                "assigned to the north line except for one weekend substitution on the "
                "airport branch. The point of the note is narrower: a single railcar "
                "can be described with different colors when the timestamps correspond "
                "to different livery phases rather than a factual contradiction."
            ),
            "reference": (
                "The commuter rail operator sent photographers and museum volunteers a "
                "note about Car 412 because the train spent one week carrying a "
                "temporary heritage wrap while the permanent fleet livery team waited "
                "for replacement decals. The note clarifies that the stainless body "
                "shell did not change ownership or route assignment, but its exterior "
                "appearance legitimately differed between the depot rollout ceremony, "
                "the regular weekday service photos, and the maintenance-bay images "
                "taken after the wrap was peeled back. Archive staff asked for the "
                "note because captions from local newspapers were already using "
                "inconsistent color descriptions, and the transit museum wanted to "
                "avoid rejecting historically accurate images simply because the car "
                "looked different across events.\n\n"
                "The museum note says Car 412 appeared silver and blue once the "
                "temporary festival wrap was peeled away and the underlying fleet "
                "livery was exposed.\n\n"
                "Another section covers operational trivia that is not central to the "
                "paint question. Car 412 still used the same traction motors after the "
                "wrap period, it kept the same wheelchair ramp module, and it remained "
                "assigned to the north line except for one weekend substitution on the "
                "airport branch. The point of the note is narrower: a single railcar "
                "can be described with different colors when the timestamps correspond "
                "to different livery phases rather than a factual contradiction."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000116"),
        sut_input_values={
            "actual": (
                "The coast guard station's buoy handbook contains a short briefing on "
                "the outer harbor beacon because apprentice coxswains kept submitting "
                "discrepancy reports after training watches logged different lamp "
                "colors for the same device. The handbook explains that the beacon "
                "uses a programmable LED array which shows one color in steady "
                "navigation mode, another during battery diagnostics, and a third when "
                "the maintenance crew switches it into identification mode while "
                "approaching by launch. All three appearances can be correct, and the "
                "station commander included annotated photographs to stop crews from "
                "treating every color change as proof that the buoy had drifted or "
                "been replaced without notice.\n\n"
                "The coxswain guide says the beacon shines white when crews trigger "
                "battery diagnostics from the service launch during daylight "
                "maintenance checks.\n\n"
                "Supplemental notes address maintenance chores around the beacon: "
                "scrape marine growth from the ladder rungs, verify the solar panel "
                "hinges still lock, and clear nesting material from the vent cap "
                "before sealing the battery compartment. A final caution tells crews "
                "to log the operating mode alongside the color observed, because a "
                "bare color report without that mode information is too incomplete to "
                "establish a contradiction on its own."
            ),
            "reference": (
                "The coast guard station's buoy handbook contains a short briefing on "
                "the outer harbor beacon because apprentice coxswains kept submitting "
                "discrepancy reports after training watches logged different lamp "
                "colors for the same device. The handbook explains that the beacon "
                "uses a programmable LED array which shows one color in steady "
                "navigation mode, another during battery diagnostics, and a third when "
                "the maintenance crew switches it into identification mode while "
                "approaching by launch. All three appearances can be correct, and the "
                "station commander included annotated photographs to stop crews from "
                "treating every color change as proof that the buoy had drifted or "
                "been replaced without notice.\n\n"
                "The coxswain guide says the beacon shines green after diagnostics "
                "finish and the buoy returns to ordinary navigation mode for outbound "
                "traffic.\n\n"
                "Supplemental notes address maintenance chores around the beacon: "
                "scrape marine growth from the ladder rungs, verify the solar panel "
                "hinges still lock, and clear nesting material from the vent cap "
                "before sealing the battery compartment. A final caution tells crews "
                "to log the operating mode alongside the color observed, because a "
                "bare color report without that mode information is too incomplete to "
                "establish a contradiction on its own."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_CONFLICTING_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_conflicting_facts_strict_mode_expected_false(case: Case) -> None:
    assert not await has_conflicting_facts(**case.sut_input_values)
