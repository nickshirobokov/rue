from uuid import UUID

import rue
from rue import Case
from rue.predicates import has_facts


HAS_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000301"),
        inputs={
            "actual": (
                "The recap says the city now carries the utility load for the downtown "
                "collection in the renovated tram depot, and it notes that curators "
                "wrote the move explanation in unusually plain language because so "
                "many donors are retirees. It also says descendants of the founder "
                "pressed for dedicated shelf space before accepting the relocation."
            ),
            "reference": (
                "The archive profile prepared for local historians says the collection "
                "now occupies a renovated streetcar depot downtown after leaving a "
                "deteriorating lodge at the fairgrounds. The same profile explains "
                "that the city agreed to absorb utility bills in exchange for public "
                "programming, that descendants of the founder negotiated for "
                "dedicated shelf space before the move, and that curators wrote the "
                "relocation brief in unusually plain language because many donors are "
                "retirees who do not read grant paperwork comfortably. The description "
                "also notes that the depot remains a public-facing research site with "
                "a freight elevator, climate control, and security upgrades framed as "
                "core reasons for the move."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000302"),
        inputs={
            "actual": (
                "The summary says that when two wide-body flights overlap, arriving "
                "international passengers still get pushed through a stopgap corridor "
                "in the late-Reagan terminal whose outbound baggage line is too small "
                "for current demand and whose restroom geometry still lags modern "
                "accessibility standards."
            ),
            "reference": (
                "The terminal profile in the airport authority packet says the "
                "building was constructed in the late 1980s and still uses an "
                "undersized outbound belt system. The profile adds that several "
                "restrooms miss current accessibility clearances and that arriving "
                "international passengers still rely on a temporary corridor whenever "
                "two wide-body flights overlap. It also records that airlines, retail "
                "tenants, and the county fire marshal all pressed management to avoid "
                "the summer holiday peak when choosing a construction calendar, but "
                "those stakeholder concerns sit alongside the more stable description "
                "of the terminal itself."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000303"),
        inputs={
            "actual": (
                "The recap says milk from member farms still feeds the Monroe curd "
                "line at the cooperative creamery that chose a broad voluntary recall "
                "after routine sampling found listeria in a floor drain beside "
                "packaging."
            ),
            "reference": (
                "The creamery backgrounder says the business is a cooperative fed by "
                "member farms in southern Wisconsin and centered on a Monroe plant "
                "with a fresh-curd packaging line. It adds that the board opted for a "
                "broad voluntary recall after routine sampling found listeria in a "
                "floor drain near that line, even though no illnesses had been "
                "reported when the notice went out. The same backgrounder mentions "
                "state inspectors, spring tourism, and reputational risk to the "
                "gift-shop business, but those details accompany the profile rather "
                "than replacing the core facts about ownership, location, and plant "
                "function."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000304"),
        inputs={
            "actual": (
                "The recap says voting control at Orion Marine Systems still sits with "
                "the founder, two siblings, and the family trust, while the company "
                "keeps making navigation sensors for ferry crews and harbor pilots "
                "from the old shipyard warehouse in Bilbao."
            ),
            "reference": (
                "The company profile for Orion Marine Systems says the manufacturer "
                "remains privately held by the founder, two siblings, and a family "
                "trust rather than outside shareholders. The same profile places the "
                "firm in Bilbao inside a converted warehouse that once served the "
                "shipyard district and explains that its main product line consists of "
                "navigation sensors sold to ferry operators, harbor pilots, and "
                "coastal survey contractors. The profile spends another paragraph on "
                "export markets and warranty terms, but the stable descriptive facts "
                "are family control, Bilbao location, and the reused shipyard building."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_facts_normal_mode_expected_true(case: Case) -> None:
    assert await has_facts(**case.input_kwargs)


HAS_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000305"),
        inputs={
            "actual": (
                "Public Works sent council members a weekend bridge status packet "
                "after a freight truck strike damaged two gusset plates and forced "
                "buses onto a detour through the warehouse district. The report walks "
                "through the temporary shoring plan, the sequence of ultrasonic "
                "inspections, and the political pressure on the mayor's office from "
                "restaurant owners who lost lunch traffic while the crossing stayed "
                "closed. Engineers explain that the bridge deck itself never slipped "
                "out of alignment, and the appendix shows how the detour added "
                "fourteen minutes to each loop during the first business day.\n\n"
                "The short recap says only that merchants asked for parking "
                "validation, the school district complained about delayed buses, and "
                "crews still need to repaint lane arrows and replace damaged barrier "
                "posts."
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
                "signed the revised load limit.\n\n"
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
                "around the riverfront."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000306"),
        inputs={
            "actual": (
                "The short recap of the housing packet focuses on elevator outages, "
                "insurance pressure after kitchen fires, and the reopening of the "
                "waiting list after renovated buildings passed inspection. It also "
                "mentions multilingual tenant notices and a weatherization grant draw "
                "schedule."
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
                "The recommendation memo calls for a six percent increase on "
                "market-rate apartments effective July 1, while senior units remain "
                "frozen for the rest of the calendar year because of the deed "
                "restrictions on the older campus.\n\n"
                "Background tables at the end of the packet list boiler replacement "
                "dates, sidewalk repair costs, and the draw schedule for a state "
                "weatherization grant. A staff note says case managers are seeing more "
                "requests for transit vouchers from residents who now travel to a "
                "suburban dialysis clinic, and procurement officers flag that one "
                "landscaping contract will expire midseason."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000307"),
        inputs={
            "actual": (
                "The harbor summary talks about neighborhood worries over truck noise, "
                "light spill from nighttime pile work, and questions about the "
                "derelict cannery sheds. It also notes sediment sampling dates, vessel "
                "counts, and ongoing lease negotiations with the cold-storage tenant."
            ),
            "reference": (
                "The harbor authority issued a grant briefing after federal reviewers "
                "asked for another clarification round on the port modernization "
                "package. The document explains that exporters want deeper berths for "
                "refrigerated cargo, tug operators want the turning basin widened "
                "before winter storms return, and the nearby fishing fleet wants "
                "written guarantees that bait trucks will keep access to the ice plant "
                "during dredging.\n\n"
                "The grant briefing says federal funds can be used for dredging the "
                "turning basin and demolishing the derelict cannery sheds, while "
                "refrigerated cargo berths will be prioritized in the first "
                "construction package.\n\n"
                "In a section on implementation, the authority says customs staffing "
                "is outside the grant, lease negotiations with the cold-storage tenant "
                "continue on a separate track, and none of the current crane operators "
                "will lose seniority if the berth redesign goes forward."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000308"),
        inputs={
            "actual": (
                "The investor recap says the annual meeting will move online, travel "
                "remains frozen except for clinical-site visits, and one floor of the "
                "old Boston office may be subleased after chemistry work shifted south."
            ),
            "reference": (
                "The biotechnology company drafted a long investor update after "
                "completing the second interim look at its respiratory-drug trial. The "
                "letter explains the study population, reminds readers that the trial "
                "enrolled patients across forty community pulmonology clinics rather "
                "than elite academic centers, and repeats that the primary endpoint "
                "tracks severe exacerbations over a full winter season.\n\n"
                "The update says the interim analysis found enough benefit in adults "
                "with severe asthma that management now plans to file for approval in "
                "that adult population before year-end, while pediatric work remains "
                "exploratory and outside the current submission.\n\n"
                "The rest of the document focuses on investor relations housekeeping. "
                "Executives say the annual meeting will move online because the audit "
                "committee chair is recovering from surgery, employee travel remains "
                "frozen except for clinical-site visits, and the company still expects "
                "to sublease one floor of its old Boston office after most chemistry "
                "work shifted to North Carolina."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_facts_normal_mode_expected_false(case: Case) -> None:
    assert not await has_facts(**case.input_kwargs)


HAS_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000309"),
        inputs={
            "actual": (
                "The recap says city payroll still keeps the river picture house open "
                "while volunteers handle repertory nights and hand-letter the "
                "marquee on its geometric facade, even though the staff roster would "
                "never support weekend screenings without that unpaid help."
            ),
            "reference": (
                "The theater profile says the cinema is municipally operated from an "
                "art-deco building on the riverfront. It explains that volunteers "
                "still program repertory nights, hand-paint the marquee inserts, and "
                "run concession shifts because the city only funds a small core staff. "
                "The same profile notes that the lobby terrazzo survived the flood of "
                "1996 and that the organ loft is now used for accessibility storage, "
                "but the stable descriptive facts remain city operation, art-deco "
                "architecture, riverfront location, and volunteer labor."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000310"),
        inputs={
            "actual": (
                "The recap says the founder and her children still hold the votes at "
                "the brick mill by the canal, and it notes that rooftop solar now "
                "carries much of the finishing line."
            ),
            "reference": (
                "The mill profile says voting control still sits with the founder and "
                "her children, the main production hall stands beside the canal, and "
                "the original brick shell remains in use despite multiple interior "
                "retrofits. It adds that the newest roof carries solar panels sized to "
                "support much of the finishing line and that the dye room was moved "
                "closer to the water-treatment plant during the last expansion. The "
                "profile gives those operational details as context for the more "
                "stable ownership, location, construction, and roof-energy facts."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000311"),
        inputs={
            "actual": (
                "The recap says the Swiss parent finished the buyout and left the "
                "Basel site doing analytical chemistry mostly for device makers."
            ),
            "reference": (
                "The laboratory profile says Alpen Holdings AG of Zurich purchased the "
                "remaining equity last year, leaving the site under Swiss ownership. "
                "It places the analytical chemistry team on the Basel campus and says "
                "most contracts come from medical-device manufacturers that need "
                "sterility and materials testing. Another paragraph covers recruitment "
                "difficulties and an unfinished loading-bay upgrade, but the enduring "
                "profile facts are Swiss ownership, Basel location, and medical-device "
                "analytics work."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000312"),
        inputs={
            "actual": (
                "The recap says recurring memberships and small gifts keep the estuary "
                "preserve running beneath a mature live-oak canopy that shades the "
                "main public loop."
            ),
            "reference": (
                "The conservancy profile says the operating budget comes primarily from "
                "memberships and small recurring donations rather than government "
                "appropriations. It places the preserve beside the estuary and notes "
                "that the main trail loop runs under a canopy of mature live oaks that "
                "define the site's microclimate. The profile also mentions birding "
                "blinds, storm-damaged fencing, and an overdue footbridge repair, but "
                "those project notes sit on top of the more durable facts about "
                "funding, estuary location, and oak-dominated landscape."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_facts_strict_mode_expected_true(case: Case) -> None:
    assert await has_facts(**case.input_kwargs)


HAS_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000313"),
        inputs={
            "actual": (
                "The donor recap says the museum is still juggling school tours, a "
                "reduced café menu, postponed gift-shop inventory work, and climate-"
                "controlled crate storage during construction."
            ),
            "reference": (
                "The museum foundation prepared a restoration memorandum for donors "
                "after water infiltrated the north gallery during January storms and "
                "stained the plaster over several nineteenth-century seascapes. The "
                "memo summarizes the roofer's findings, the conservator's moisture "
                "readings, and the legal review of the original construction contract "
                "from 1997, which turned out to exclude damage caused by deferred "
                "maintenance.\n\n"
                "The board memo says the preservation rebate will cover forty percent "
                "of the roof project, the museum will replace the entire copper skin "
                "over the north gallery this summer, and the maritime exhibition will "
                "open on schedule after a brief one-week install delay.\n\n"
                "Later paragraphs cover the museum's contingency planning. Staff will "
                "shift school tours into the sculpture court if the western stairwell "
                "has to close, the café will use a reduced menu while dust barriers "
                "are installed, and the gift shop plans to postpone its inventory "
                "audit until the roof contractors have left the loading dock."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000314"),
        inputs={
            "actual": (
                "The memo recap says the archive still needs volunteer parking, "
                "oversize-map delivery access, a usable freight elevator, and a side "
                "agreement with the transit museum over basement storage."
            ),
            "reference": (
                "A regional history archive assembled a relocation brief after its "
                "volunteer board agreed to leave a crumbling lodge on the edge of the "
                "fairgrounds and move collections into a renovated streetcar depot "
                "downtown. The brief walks through humidity readings in the map room, "
                "explains how the city offered to absorb utility bills in exchange for "
                "public programming, and recounts months of negotiation with "
                "descendants of the archive's founder who were worried that family "
                "papers would lose dedicated shelf space after the move.\n\n"
                "The relocation brief says the city accepted title to the archive "
                "building, will pay the depot utilities for at least five years, and "
                "has agreed to appoint the new director once the volunteer board "
                "dissolves.\n\n"
                "The annexes cover practical matters such as volunteer parking, "
                "delivery access for oversize map cases, and whether the research desk "
                "can stay open during the week the freight elevator is inspected."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000315"),
        inputs={
            "actual": (
                "The industry memo recap says replacement parts need airport cargo "
                "apron access, rural lawmakers are protective of bridge money, and "
                "environmental groups want solvent-recovery plans disclosed publicly."
            ),
            "reference": (
                "The governor's office commissioned a strategy memo on semiconductor "
                "expansion because two equipment suppliers are considering sites near "
                "the inland airport and lawmakers want a clear picture of subsidy "
                "exposure before the next budget session. The memo compares power "
                "demand across fabrication steps, outlines the mineral-processing "
                "bottlenecks for photoresist chemicals and specialty gases, and "
                "summarizes federal export-control constraints that could limit which "
                "tools are allowed on the proposed campus.\n\n"
                "The strategy memo treats export controls as a major constraint on "
                "which tools can be installed, says the state would need a large "
                "subsidy package to compete, and warns that the labor shortage among "
                "industrial electricians is a serious risk to the project timeline.\n\n"
                "Near the end, the memo shifts to politics. Rural legislators want "
                "assurances that road upgrades serving the plant will not crowd out "
                "bridge repairs in their districts, environmental groups demand a "
                "public accounting of solvent recovery plans, and the airport "
                "authority is lobbying for cargo apron improvements."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000316"),
        inputs={
            "actual": (
                "The memo recap says plaintiff forums fueled confusion, call-center "
                "staff extended hours after the leak, and outside counsel still "
                "expects to file a sealed fee petition."
            ),
            "reference": (
                "The regional insurer circulated a settlement memorandum after a "
                "judge ordered another mediation session in the long-running wildfire "
                "smoke business-loss case. Claims managers wrote the memo for "
                "franchise owners who had heard conflicting rumors about who would be "
                "paid first, whether future appeals were still possible, and how the "
                "company planned to treat shops that closed for only part of the "
                "evacuation period.\n\n"
                "The memo says the settlement covers 312 franchisees, requires "
                "individual payments of $18,750 to be wired by Friday, bars any "
                "appeal by either side, and obligates the chief executive to issue a "
                "public apology once the judge signs the dismissal order.\n\n"
                "The final pages are administrative rather than substantive. They list "
                "which claims offices will extend phone hours after the notice is "
                "sent, how the bank will handle returned wires, and when outside "
                "defense counsel expects to file a sealed fee petition."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_facts_strict_mode_expected_false(case: Case) -> None:
    assert not await has_facts(**case.input_kwargs)
