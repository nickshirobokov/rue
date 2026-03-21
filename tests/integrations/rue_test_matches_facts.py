from uuid import UUID

import rue
from rue import Case
from rue.predicates import matches_facts


MATCHES_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000501"),
        sut_input_values={
            "actual": (
                "The marine surveyor's report on the commuter ferry explains that the "
                "vessel stayed on the south-bay run throughout the winter overhaul, "
                "kept its hybrid propulsion package, and reopened with the same "
                "passenger layout after non-skid coating was reapplied to the upper "
                "deck. The report also notes that the boarding ramps were realigned, "
                "life-ring canisters were replaced, and the galley refrigerators were "
                "rebuilt before service resumed. In the exterior section, the surveyor "
                "describes the ferry as carrying a navy hull with white superstructure "
                "panels and reflective emergency striping along the boarding gate."
            ),
            "reference": (
                "The marine surveyor's report on the commuter ferry explains that the "
                "vessel stayed on the south-bay run throughout the winter overhaul, "
                "kept its hybrid propulsion package, and reopened with the same "
                "passenger layout after non-skid coating was reapplied to the upper "
                "deck. The report also notes that the boarding ramps were realigned, "
                "life-ring canisters were replaced, and the galley refrigerators were "
                "rebuilt before service resumed. In the exterior section, the surveyor "
                "describes the ferry as carrying a dark blue hull with white "
                "superstructure panels and reflective emergency striping along the "
                "boarding gate."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000502"),
        sut_input_values={
            "actual": (
                "The clinic renovation brief says the waiting room still faces the "
                "courtyard, the reception desk was lowered to meet accessibility "
                "clearances, and the pediatric alcove now has built-in cabinets for "
                "loaner hearing-protection kits. It also notes that the HVAC diffusers "
                "were moved away from the immunization chairs and that the old tile "
                "base was replaced with welded vinyl for infection control. The brief "
                "describes the finished walls as cream, with oak trim around the check-"
                "in desk and a muted mural by the blood-pressure station."
            ),
            "reference": (
                "The clinic renovation brief says the waiting room still faces the "
                "courtyard, the reception desk was lowered to meet accessibility "
                "clearances, and the pediatric alcove now has built-in cabinets for "
                "loaner hearing-protection kits. It also notes that the HVAC diffusers "
                "were moved away from the immunization chairs and that the old tile "
                "base was replaced with welded vinyl for infection control. The brief "
                "describes the finished walls as off-white, with oak trim around the "
                "check-in desk and a muted mural by the blood-pressure station."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000503"),
        sut_input_values={
            "actual": (
                "The airport safety review says the weather mast remains anchored on "
                "the eastern berm, feeds data into the same wind-shear console as last "
                "season, and was serviced without disrupting dawn departures. The "
                "review notes that the anemometer cups were replaced, a lightning "
                "ground was added, and the maintenance crew repainted the ladder cage "
                "before the winter rains arrived. It identifies the obstruction beacon "
                "at the top of the mast as crimson and says the lamp flashes at the "
                "same interval specified in the prior year's maintenance order."
            ),
            "reference": (
                "The airport safety review says the weather mast remains anchored on "
                "the eastern berm, feeds data into the same wind-shear console as last "
                "season, and was serviced without disrupting dawn departures. The "
                "review notes that the anemometer cups were replaced, a lightning "
                "ground was added, and the maintenance crew repainted the ladder cage "
                "before the winter rains arrived. It identifies the obstruction beacon "
                "at the top of the mast as deep red and says the lamp flashes at the "
                "same interval specified in the prior year's maintenance order."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000504"),
        sut_input_values={
            "actual": (
                "The downtown market preservation note says the produce hall still "
                "uses cast-iron columns from the original structure, that the roof "
                "trusses were sandblasted instead of replaced, and that the arcade "
                "will reopen before the autumn harvest fair if the permit queue keeps "
                "moving. The note also records that stall fronts were renumbered, old "
                "fluorescents were swapped for pendant fixtures, and the awnings were "
                "restitched after a windstorm tore one corner loose. It describes the "
                "awning cloth as charcoal with cream lettering and narrow brass edge "
                "rails."
            ),
            "reference": (
                "The downtown market preservation note says the produce hall still "
                "uses cast-iron columns from the original structure, that the roof "
                "trusses were sandblasted instead of replaced, and that the arcade "
                "will reopen before the autumn harvest fair if the permit queue keeps "
                "moving. The note also records that stall fronts were renumbered, old "
                "fluorescents were swapped for pendant fixtures, and the awnings were "
                "restitched after a windstorm tore one corner loose. It describes the "
                "awning cloth as dark gray with cream lettering and narrow brass edge "
                "rails."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*MATCHES_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_matches_facts_normal_mode_expected_true(case: Case) -> None:
    assert await matches_facts(**case.sut_input_values)


MATCHES_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000505"),
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
                "overlap.\n\n"
                "The operations section says Gate C will close for six weeks beginning "
                "on August 12, the customs hall rebuild has been deferred until spring "
                "2027, and international arrivals will keep using the temporary "
                "east-corridor route until the conveyor replacement is finished."
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
                "overlap.\n\n"
                "The operations section says Gate C will remain open through the "
                "holiday schedule, the customs hall rebuild will begin this October, "
                "and international arrivals will be rerouted to the south concourse as "
                "soon as demolition fencing goes up."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000506"),
        sut_input_values={
            "actual": (
                "Public Works sent council members a weekend bridge status packet "
                "after a freight truck strike damaged two gusset plates and forced "
                "buses onto a detour through the warehouse district. Engineers explain "
                "that the bridge deck itself never slipped out of alignment, and the "
                "appendix shows how the detour added fourteen minutes to each loop "
                "during the first business day.\n\n"
                "According to the status packet, engineers signed the final load test "
                "before dawn on Monday, buses returned to their usual route by 11:30 "
                "that morning, and the city reopened all four traffic lanes before the "
                "lunch rush."
            ),
            "reference": (
                "Public Works sent council members a weekend bridge status packet "
                "after a freight truck strike damaged two gusset plates and forced "
                "buses onto a detour through the warehouse district. Engineers explain "
                "that the bridge deck itself never slipped out of alignment, and the "
                "appendix shows how the detour added fourteen minutes to each loop "
                "during the first business day.\n\n"
                "According to the status packet, engineers withheld approval all day "
                "Monday, buses stayed on detour until Tuesday afternoon, and the city "
                "kept the bridge fully closed to general traffic until the next day."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000507"),
        sut_input_values={
            "actual": (
                "The biotechnology company drafted a long investor update after "
                "completing the second interim look at its respiratory-drug trial. The "
                "letter explains the study population, repeats that the primary "
                "endpoint tracks severe exacerbations over a full winter season, and "
                "describes manufacturing work at the New Mexico fill-finish plant.\n\n"
                "The update says the interim analysis found enough benefit in adults "
                "with severe asthma that management now plans to file for approval in "
                "that adult population before year-end."
            ),
            "reference": (
                "The biotechnology company drafted a long investor update after "
                "completing the second interim look at its respiratory-drug trial. The "
                "letter explains the study population, repeats that the primary "
                "endpoint tracks severe exacerbations over a full winter season, and "
                "describes manufacturing work at the New Mexico fill-finish plant.\n\n"
                "The update says the company will pursue an adolescent-only filing "
                "because the adult cohort failed to separate from placebo, and "
                "executives describe the adult program as unlikely to move forward "
                "without a new Phase Three study."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000508"),
        sut_input_values={
            "actual": (
                "The housing authority board packet for April combines a rent "
                "recommendation memo, a capital-maintenance forecast, and a "
                "resident-services update because commissioners wanted a single "
                "document before voting on next year's budget. Staff describe elevator "
                "outages in the oldest towers, explain why insurance premiums rose "
                "after two kitchen fires, and note that the waiting list reopened for "
                "the first time in eighteen months after three renovated buildings "
                "passed inspection.\n\n"
                "The recommendation memo calls for a six percent increase on "
                "market-rate apartments effective July 1, while senior units remain "
                "frozen for the rest of the calendar year."
            ),
            "reference": (
                "The housing authority board packet for April combines a rent "
                "recommendation memo, a capital-maintenance forecast, and a "
                "resident-services update because commissioners wanted a single "
                "document before voting on next year's budget. Staff describe elevator "
                "outages in the oldest towers, explain why insurance premiums rose "
                "after two kitchen fires, and note that the waiting list reopened for "
                "the first time in eighteen months after three renovated buildings "
                "passed inspection.\n\n"
                "The recommendation memo calls for a full rent freeze across every "
                "property through December 31, including market-rate apartments, "
                "senior units, and the mixed-finance redevelopment sites that reopened "
                "this spring."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*MATCHES_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_matches_facts_normal_mode_expected_false(case: Case) -> None:
    assert not await matches_facts(**case.sut_input_values)


MATCHES_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000509"),
        sut_input_values={
            "actual": (
                "The museum registrar's packing memo says the outbound crate for the "
                "loaned astrolabe keeps the same shock sensors, silica canisters, and "
                "custom foam cradle used last season. It also notes that the courier "
                "packet stayed in the lid sleeve and that customs paperwork was taped "
                "under the right-side handle before the truck left. The visible finish "
                "on the crate is described as turquoise, applied over the same marine-"
                "grade plywood panels used on the previous trip."
            ),
            "reference": (
                "The museum registrar's packing memo says the outbound crate for the "
                "loaned astrolabe keeps the same shock sensors, silica canisters, and "
                "custom foam cradle used last season. It also notes that the courier "
                "packet stayed in the lid sleeve and that customs paperwork was taped "
                "under the right-side handle before the truck left. The visible finish "
                "on the crate is described as blue-green, applied over the same "
                "marine-grade plywood panels used on the previous trip."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000510"),
        sut_input_values={
            "actual": (
                "The orchard logistics note says Truck 17 still handles the north "
                "route, keeps the refrigerated insert installed through pear season, "
                "and had its rear liftgate rewired after a mechanic traced a fault to "
                "a corroded relay. The note says the cab is silver-gray and that the "
                "replacement door decals were delayed by one week because the printer "
                "missed the original farm crest."
            ),
            "reference": (
                "The orchard logistics note says Truck 17 still handles the north "
                "route, keeps the refrigerated insert installed through pear season, "
                "and had its rear liftgate rewired after a mechanic traced a fault to "
                "a corroded relay. The note says the cab is gray-silver and that the "
                "replacement door decals were delayed by one week because the printer "
                "missed the original farm crest."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000511"),
        sut_input_values={
            "actual": (
                "The university stadium maintenance order says the seating bowl kept "
                "its original numbering, the aisle lights were upgraded to LED strips, "
                "and the west vomitory handrails were powder-coated before the season "
                "opener. It describes the newly replaced lower-bowl seats as maroon "
                "and notes that the manufacturer had to retool one mold after the "
                "first shipment arrived with warped cup-holder mounts."
            ),
            "reference": (
                "The university stadium maintenance order says the seating bowl kept "
                "its original numbering, the aisle lights were upgraded to LED strips, "
                "and the west vomitory handrails were powder-coated before the season "
                "opener. It describes the newly replaced lower-bowl seats as deep "
                "burgundy and notes that the manufacturer had to retool one mold after "
                "the first shipment arrived with warped cup-holder mounts."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000512"),
        sut_input_values={
            "actual": (
                "The conservation worksheet says the seventeenth-century jar still has "
                "the same chipped foot ring, the same repaired shoulder crack, and the "
                "same cork-padded travel collar fitted after the Zurich exhibition. It "
                "also says the exterior glaze reads midnight blue under the gallery's "
                "neutral lamps and that no overpaint was found around the restored "
                "cartouche."
            ),
            "reference": (
                "The conservation worksheet says the seventeenth-century jar still has "
                "the same chipped foot ring, the same repaired shoulder crack, and the "
                "same cork-padded travel collar fitted after the Zurich exhibition. It "
                "also says the exterior glaze reads blue-black under the gallery's "
                "neutral lamps and that no overpaint was found around the restored "
                "cartouche."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*MATCHES_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_matches_facts_strict_mode_expected_true(case: Case) -> None:
    assert await matches_facts(**case.sut_input_values)


MATCHES_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000513"),
        sut_input_values={
            "actual": (
                "The museum foundation prepared a restoration memorandum for donors "
                "after water infiltrated the north gallery during January storms and "
                "stained the plaster over several nineteenth-century seascapes.\n\n"
                "The board memo says the preservation rebate will cover forty percent "
                "of the roof project, the museum will replace the entire copper skin "
                "over the north gallery this summer, and the maritime exhibition will "
                "open on schedule after a brief one-week install delay."
            ),
            "reference": (
                "The museum foundation prepared a restoration memorandum for donors "
                "after water infiltrated the north gallery during January storms and "
                "stained the plaster over several nineteenth-century seascapes.\n\n"
                "The board memo says the preservation rebate was denied, only patch "
                "repairs will be performed on the north roof before winter, and the "
                "maritime exhibition must be postponed because the gallery cannot "
                "reopen in time for incoming loans."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000514"),
        sut_input_values={
            "actual": (
                "The harbor authority issued a grant briefing after federal reviewers "
                "asked for another clarification round on the port modernization "
                "package.\n\n"
                "The grant briefing says federal funds can be used for dredging the "
                "turning basin and demolishing the derelict cannery sheds, while "
                "refrigerated cargo berths will be prioritized in the first "
                "construction package."
            ),
            "reference": (
                "The harbor authority issued a grant briefing after federal reviewers "
                "asked for another clarification round on the port modernization "
                "package.\n\n"
                "The grant briefing says federal funds cannot be used for dredging or "
                "demolition at the cannery edge, and the first package is limited to "
                "upland roadwork with berth expansion pushed into a later phase."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000515"),
        sut_input_values={
            "actual": (
                "A regional history archive assembled a relocation brief after its "
                "volunteer board agreed to move collections into a renovated streetcar "
                "depot downtown.\n\n"
                "The relocation brief says the city accepted title to the archive "
                "building, will pay the depot utilities for at least five years, and "
                "has agreed to appoint the new director once the volunteer board "
                "dissolves."
            ),
            "reference": (
                "A regional history archive assembled a relocation brief after its "
                "volunteer board agreed to move collections into a renovated streetcar "
                "depot downtown.\n\n"
                "The relocation brief says the archive will remain an entirely "
                "independent tenant, the city will not assume utility costs, and the "
                "volunteer board will continue appointing its own director after the "
                "move."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000516"),
        sut_input_values={
            "actual": (
                "The governor's office commissioned a strategy memo on semiconductor "
                "expansion because two equipment suppliers are considering sites near "
                "the inland airport.\n\n"
                "The strategy memo treats export controls as a major constraint on "
                "which tools can be installed, says the state would need a large "
                "subsidy package to compete, and warns that the labor shortage among "
                "industrial electricians is a serious risk to the project timeline."
            ),
            "reference": (
                "The governor's office commissioned a strategy memo on semiconductor "
                "expansion because two equipment suppliers are considering sites near "
                "the inland airport.\n\n"
                "The strategy memo says export controls are largely irrelevant to the "
                "proposed tool set, rejects the need for sizable subsidies, and "
                "describes the skilled-labor pipeline as already adequate for "
                "immediate build-out."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*MATCHES_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_matches_facts_strict_mode_expected_false(case: Case) -> None:
    assert not await matches_facts(**case.sut_input_values)
