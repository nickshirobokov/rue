from uuid import UUID

import rue
from rue import Case
from rue.predicates import has_unsupported_facts


HAS_UNSUPPORTED_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000201"),
        inputs={
            "actual": (
                "The regional insurer circulated a settlement memorandum after a "
                "judge ordered another mediation session in the long-running wildfire "
                "smoke business-loss case. Claims managers wrote the memo for "
                "franchise owners who had heard conflicting rumors about who would be "
                "paid first, whether future appeals were still possible, and how the "
                "company planned to treat shops that closed for only part of the "
                "evacuation period. The memo summarizes testimony from forensic "
                "accountants, explains why the court refused to certify a broader "
                "property-damage subclass, and notes that a separate dispute over "
                "broker commissions remains unresolved. Operations staff asked legal "
                "to write the update in plain English so field adjusters would stop "
                "forwarding screenshots of half-true messages from plaintiff forums "
                "and local business associations.\n\n"
                "The memo says the settlement covers 312 franchisees, requires "
                "individual payments of $18,750 to be wired by Friday, bars any "
                "appeal by either side, and obligates the chief executive to issue a "
                "public apology once the judge signs the dismissal order.\n\n"
                "The final pages are administrative rather than substantive. They list "
                "which claims offices will extend phone hours after the notice is "
                "sent, how the bank will handle returned wires, and when outside "
                "defense counsel expects to file a sealed fee petition. There is also "
                "a short paragraph on staff wellness because call-center teams handled "
                "a surge of angry inquiries after the mediation date leaked. Those "
                "side notes matter internally, but they do not change the actual "
                "settlement terms and obligations described in the main section."
            ),
            "reference": (
                "The regional insurer circulated a settlement memorandum after a "
                "judge ordered another mediation session in the long-running wildfire "
                "smoke business-loss case. Claims managers wrote the memo for "
                "franchise owners who had heard conflicting rumors about who would be "
                "paid first, whether future appeals were still possible, and how the "
                "company planned to treat shops that closed for only part of the "
                "evacuation period. The memo summarizes testimony from forensic "
                "accountants, explains why the court refused to certify a broader "
                "property-damage subclass, and notes that a separate dispute over "
                "broker commissions remains unresolved. Operations staff asked legal "
                "to write the update in plain English so field adjusters would stop "
                "forwarding screenshots of half-true messages from plaintiff forums "
                "and local business associations.\n\n"
                "The memo says the settlement covers 312 franchisees and requires "
                "payment to class members once the court approves the final papers.\n\n"
                "The final pages are administrative rather than substantive. They list "
                "which claims offices will extend phone hours after the notice is "
                "sent, how the bank will handle returned wires, and when outside "
                "defense counsel expects to file a sealed fee petition. There is also "
                "a short paragraph on staff wellness because call-center teams handled "
                "a surge of angry inquiries after the mediation date leaked. Those "
                "side notes matter internally, but they do not change the actual "
                "settlement terms and obligations described in the main section."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000202"),
        inputs={
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
                "The latest summary says the grant will also reimburse the purchase of "
                "two refrigerated cranes, require nighttime truck curfews beginning in "
                "July, and cover a temporary tax abatement promised by the mayor to "
                "the cold-storage tenant while demolition fencing blocks part of the "
                "yard.\n\n"
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
                "The briefing says federal reviewers are still evaluating dredging, "
                "berth geometry, and demolition access, while customs staffing and "
                "tenant lease talks remain outside the grant package.\n\n"
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
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000203"),
        inputs={
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
                "The investor summary adds that the company has already secured an FDA "
                "advisory-committee slot for September 18, that the chief financial "
                "officer will resign the same day results are presented, and that the "
                "board has authorized a special dividend if the filing is accepted "
                "before year-end.\n\n"
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
                "The update says management is still evaluating next steps after the "
                "interim readout and has not yet described any regulatory timetable or "
                "capital-allocation change tied to the data.\n\n"
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
        id=UUID("00000000-0000-0000-0000-000000000204"),
        inputs={
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
                "The revised donor brief says the museum will keep the café closed for "
                "six months, extend naming rights on the north gallery to a new "
                "sponsor, and require lenders from Rotterdam to buy separate "
                "storm-insurance riders before any paintings are uncrated.\n\n"
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
                "The donor memo focuses on roof scope, preservation rebates, gallery "
                "timing, and handling plans for incoming maritime-art loans.\n\n"
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
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_UNSUPPORTED_FACTS_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_unsupported_facts_normal_mode_expected_true(case: Case) -> None:
    assert await has_unsupported_facts(**case.input_kwargs)


HAS_UNSUPPORTED_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000205"),
        inputs={
            "actual": (
                "The recap portrays the archive as taxpayer-backed, streetcar-depot "
                "based, founder-family accommodating, shelf-space protective, and "
                "donor-retiree oriented. It also treats the collection as city-housed "
                "and utility-underwritten rather than as a private archive simply "
                "renting downtown space."
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
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000206"),
        inputs={
            "actual": (
                "The summary portrays the creamery as farmer-owned, recall-shadowed, "
                "fresh-curd centered, regulator-scrutinized, and tourism-exposed. It "
                "also frames the plant as member-farm fed, all-store-recall oriented, "
                "gift-shop vulnerable, and reputation-sensitive during the same spring "
                "season when visitor traffic usually doubles and local press attention "
                "tends to spike."
            ),
            "reference": (
                "The cooperative creamery distributed a recall briefing after routine "
                "sampling found listeria in a floor drain near the fresh-curd "
                "packaging line. The packet explains that no illnesses had been "
                "reported when the recall notice went out, but the board chose a broad "
                "voluntary action because one supermarket chain demanded a single "
                "all-stores statement instead of piecemeal withdrawal notices. Plant "
                "managers describe sanitation steps taken over the weekend, summarize "
                "conversations with state inspectors, and warn that milk intake from "
                "member farms may have to be diverted to shelf-stable products until "
                "environmental swabs come back clean. A separate timeline notes that "
                "spring tourism usually doubles gift-shop traffic, making reputational "
                "damage a live concern even if the contamination never reached sealed "
                "packages.\n\n"
                "The closing pages focus on supplier relations and cash flow. Finance "
                "staff are negotiating a short bridge line with the local bank, the "
                "union wants written assurances that hourly workers will not lose "
                "health coverage during any pause in curd production, and marketing "
                "has already cancelled a regional radio buy tied to the summer cheese "
                "festival. Those downstream consequences matter, but they are distinct "
                "from the factual claims the recall briefing makes about source "
                "tracing, plant status, and the products included in the withdrawal."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000207"),
        inputs={
            "actual": (
                "The overview describes the proposed supplier campus as airport-"
                "adjacent, power-hungry, specialty-gas dependent, and exposed to "
                "export controls. It adds that industrial electricians are scarce and "
                "that community colleges are racing to stand up certificate programs "
                "before site work begins. The recap also treats the campus as cargo-"
                "airport reliant, infrastructure-heavy, and workforce-thin in a way "
                "that makes the project sound structurally dependent on utility, "
                "training, and trade-policy support."
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
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000208"),
        inputs={
            "actual": (
                "The summary portrays the terminal as late-1980s, undersized-belted, "
                "accessibility-deficient, corridor-dependent, and ceramic-panel "
                "conscious. The closing appendix does not change that picture, and "
                "the recap continues to treat the building as east-concourse bound, "
                "holiday-sensitive, and operationally shaped by the same inherited "
                "circulation limits described in the main packet."
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
)


@rue.iter_cases(*HAS_UNSUPPORTED_FACTS_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_unsupported_facts_normal_mode_expected_false(case: Case) -> None:
    assert not await has_unsupported_facts(**case.input_kwargs)


HAS_UNSUPPORTED_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000209"),
        inputs={
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
                "A separate summary of the board packet says the authority will pair "
                "its rent decision with a temporary eviction moratorium, seek state "
                "receivership for the oldest tower, and close two neighborhood "
                "libraries to free up maintenance cash for the housing budget.\n\n"
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
                "The packet focuses on rents, maintenance, insurance, wait-list "
                "reopening, and deed restrictions at the senior campus.\n\n"
                "Background tables at the end of the packet list boiler replacement "
                "dates, sidewalk repair costs, and the draw schedule for a state "
                "weatherization grant. A staff note says case managers are seeing more "
                "requests for transit vouchers from residents who now travel to a "
                "suburban dialysis clinic, and procurement officers flag that one "
                "landscaping contract will expire midseason. Those details provide "
                "context for the board's vote, but they do not alter the core policy "
                "recommendation laid out in the main memorandum."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000210"),
        inputs={
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
                "The revised summary says the airport will also station a TSA canine "
                "team in the south checkpoint, waive landing fees for one low-cost "
                "carrier during construction, and relocate the public art wall to the "
                "hotel shuttle loop before demolition begins.\n\n"
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
                "The donor-facing summary discusses gates, customs routing, security "
                "checkpoint continuity, snow-removal staging, and the future of the "
                "public art wall from the commuter wing.\n\n"
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
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000211"),
        inputs={
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
                "The short recap says the museum will also keep the café dark for half "
                "a year, reopen the gift shop only to members, and ask foreign lenders "
                "to secure separate storm riders before any crates are unpacked.\n\n"
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
                "The memo deals with storm damage, roof scope, preservation rebates, "
                "and how the summer maritime exhibition can proceed during repairs.\n\n"
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
        id=UUID("00000000-0000-0000-0000-000000000212"),
        inputs={
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
                "The latest recap says the authority will issue a backup bond against "
                "cost overruns, obtain a no-strike pledge from the crane union, and "
                "cancel the harbor festival outright once demolition fencing goes up.\n\n"
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
                "The briefing discusses dredging, berth layout, tenant access, "
                "sediment sampling, and whether the harbor festival might be moved if "
                "demolition permits are still active in August.\n\n"
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
)


@rue.iter_cases(*HAS_UNSUPPORTED_FACTS_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_unsupported_facts_strict_mode_expected_true(case: Case) -> None:
    assert await has_unsupported_facts(**case.input_kwargs)


HAS_UNSUPPORTED_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000213"),
        inputs={
            "actual": (
                "The recap portrays the archive as taxpayer-backed, streetcar-depot "
                "based, founder-family accommodating, shelf-space protective, and "
                "donor-retiree oriented. It also treats the collection as city-housed, "
                "utility-underwritten, and research-access conscious rather than as a "
                "private archive simply renting downtown space."
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
        id=UUID("00000000-0000-0000-0000-000000000214"),
        inputs={
            "actual": (
                "The recap describes the drug program as inhaled, winter-endpoint "
                "driven, plant-tethered, analyst-confused, and device-manufacturer "
                "facing."
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
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000215"),
        inputs={
            "actual": (
                "The recap describes the senior campus as deed-restricted and the "
                "authority as multilingual in tenant communication because notices "
                "already have to work in Spanish, Vietnamese, and Somali. It also "
                "mentions elevator failures, insurance pressure after kitchen fires, "
                "and the waiting-list reopening after renovated buildings cleared "
                "inspection. The same recap makes the system sound weatherization-"
                "linked and senior-campus constrained in a way that ties those facts "
                "back to budget pressure rather than treating them as isolated notes."
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
                "Background tables at the end of the packet list boiler replacement "
                "dates, sidewalk repair costs, and the draw schedule for a state "
                "weatherization grant. A staff note says case managers are seeing more "
                "requests for transit vouchers from residents who now travel to a "
                "suburban dialysis clinic, and procurement officers flag that one "
                "landscaping contract will expire midseason. Those details provide "
                "context for the board's vote, but they do not alter the core policy "
                "recommendation laid out in the main memorandum."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000216"),
        inputs={
            "actual": (
                "The summary portrays the terminal as late-1980s, undersized-belted, "
                "accessibility-deficient, corridor-dependent, and ceramic-panel "
                "conscious. It also treats the building as holiday-sensitive and east-"
                "concourse bound, with the inherited commuter-wing panels folded into "
                "the terminal's standing identity instead of described as a separate "
                "appendix item."
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
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_UNSUPPORTED_FACTS_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_unsupported_facts_strict_mode_expected_false(case: Case) -> None:
    assert not await has_unsupported_facts(**case.input_kwargs)
