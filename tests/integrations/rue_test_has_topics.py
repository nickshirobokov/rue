from uuid import UUID

import rue
from rue import Case
from rue.predicates import has_topics


HAS_TOPICS_NORMAL_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000401"),
        inputs={
            "actual": (
                "The outage is electrical."
            ),
            "reference": (
                "Required topic: electrical outages and restoration. Reviewers mean "
                "the practical topic of power loss, fault isolation, transfer-switch "
                "failure, temporary lighting, elevator shutdowns, cooling support, "
                "repair sequencing, and the way a building is stabilized while crews "
                "bring service back online. A response can mention panel rooms, "
                "generator behavior, security staffing, resident communication, or the "
                "timing of the next facilities update, but the core topic remains an "
                "electrical outage and the restoration work around it. The scoring "
                "guide treats that entire cluster as one topic rather than separate "
                "maintenance, safety, and communications subjects."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000402"),
        inputs={
            "actual": (
                "Respiratory drug trial."
            ),
            "reference": (
                "Required topic: respiratory drug trials. In this scoring guide, that "
                "topic includes study population design, endpoints, regulators, "
                "manufacturing readiness, interim data interpretation, and the "
                "difference between adult and pediatric strategies after a readout. "
                "Writers may mention analysts, conference abstracts, or fill-finish "
                "plants, but the underlying topic is still clinical development for a "
                "respiratory medicine and the practical steps between trial results "
                "and a possible filing. A fully developed answer might discuss why "
                "community pulmonology clinics were used, why investors can confuse an "
                "inhaled therapy with an older antibody asset, why a New Mexico plant "
                "matters for commercialization, and how an adult filing strategy can "
                "diverge from a pediatric exploration even when both come out of the "
                "same data package. Those details remain inside one respiratory-trial "
                "topic."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000403"),
        inputs={
            "actual": (
                "Archive relocation."
            ),
            "reference": (
                "Required topic: archive relocation. The intended scope includes "
                "moving collections between buildings, preserving research access, "
                "handling donor and descendant concerns, working through utilities and "
                "security, and explaining how a new site changes public programming. "
                "Mentions of freight elevators, loading bays, climate control, and "
                "building history all count as supporting material within the same "
                "archive-relocation topic rather than separate subjects. Reviewers "
                "expect the answer to recognize that moving an archive is not only a "
                "real-estate change but also a question about conservation risk, "
                "family trust, donor communications, map-case access, research-desk "
                "continuity, and how a city or partner institution might reshape the "
                "public role of the collection once it leaves an older building. Those "
                "subpoints should still be treated as one coherent topic."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000404"),
        inputs={
            "actual": (
                "Semiconductor industrial policy."
            ),
            "reference": (
                "Required topic: semiconductor industrial policy. That topic covers "
                "how governments evaluate fab or supplier expansion, how export "
                "controls and subsidies shape the commercial case, what infrastructure "
                "and workforce constraints dominate project timelines, and how "
                "supporting systems such as airports, roads, power, water, and "
                "community colleges interact with an advanced-manufacturing push. "
                "Environmental objections and rural political concerns still sit under "
                "the same industrial-policy umbrella. A strong answer could mention "
                "specialty gases, photoresist bottlenecks, cargo-apron needs, road "
                "upgrades, electrician shortages, subsidy exposure, and the question of "
                "which tools export rules would even allow on site, but the rubric "
                "still treats those as one combined policy topic rather than a basket "
                "of disconnected themes."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_TOPICS_NORMAL_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_topics_normal_mode_expected_true(case: Case) -> None:
    assert await has_topics(**case.input_kwargs)


HAS_TOPICS_NORMAL_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000405"),
        inputs={
            "actual": (
                "Public Works sent council members a weekend bridge status packet "
                "after a freight truck strike damaged two gusset plates and forced "
                "buses onto a detour through the warehouse district. The report walks "
                "through temporary shoring, ultrasonic inspections, merchant demands "
                "for parking validation, school complaints about delayed buses, and "
                "the repainting of lane arrows and barrier posts once traffic returns. "
                "Every paragraph is about reopening the bridge safely and managing the "
                "detour's local consequences."
            ),
            "reference": (
                "Required topics: medieval manuscript illumination, monastic Latin "
                "paleography, and parchment restoration chemistry. A passing response "
                "should discuss scribal hands, decorative pigments, archival repair "
                "techniques, and the material science behind preserving religious "
                "manuscripts rather than roads, transit, or local traffic control."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000406"),
        inputs={
            "actual": (
                "The housing authority board packet focuses on elevator outages, "
                "insurance premiums after kitchen fires, multilingual tenant notices, "
                "weatherization grant draws, transit vouchers for dialysis trips, and "
                "the timing of a landscaping contract renewal. The packet does not "
                "shift into laboratory methods, marine ecology, or excavation "
                "practice; it stays in the narrow lane of public-housing operations."
            ),
            "reference": (
                "Required topics: deep-sea hydrothermal vents, submersible robotics, "
                "and abyssal biodiversity surveying. A complete answer would need to "
                "talk about remotely operated vehicles, mineral chimneys, vent "
                "communities, sampling methods, and oceanographic expedition planning."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000407"),
        inputs={
            "actual": (
                "The museum donor memo is about roof leaks, preservation rebates, "
                "maritime-art loan schedules, school tours shifting to the sculpture "
                "court, gift-shop inventory delays, and crate-handling logistics. It "
                "is a facilities and exhibition document, not an analysis of lending "
                "markets, reserve policy, or interbank plumbing."
            ),
            "reference": (
                "Required topics: repo markets, central-bank standing facilities, and "
                "bank reserve transmission. Reviewers want discussion of collateral, "
                "overnight funding, liquidity backstops, and how reserve conditions "
                "affect bank behavior across the financial system."
            ),
            "strict": False,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000408"),
        inputs={
            "actual": (
                "The creamery recall briefing talks about listeria, a floor drain near "
                "the fresh-curd line, supermarket demands for a single withdrawal "
                "notice, sanitation steps, member-farm milk diversion, and the risk of "
                "gift-shop losses during spring tourism. Nothing in it turns toward "
                "constitutional doctrine, election remedies, or comparative federalism."
            ),
            "reference": (
                "Required topics: constitutional emergency powers, comparative "
                "federalism, and judicial review of executive decrees. A passing "
                "response should engage with constitutional structure, emergency "
                "statutes, separation of powers, and court supervision of executive "
                "action during crises."
            ),
            "strict": False,
        },
    ),
)


@rue.iter_cases(*HAS_TOPICS_NORMAL_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_topics_normal_mode_expected_false(case: Case) -> None:
    assert not await has_topics(**case.input_kwargs)


HAS_TOPICS_STRICT_MODE_EXPECTED_TRUE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000409"),
        inputs={
            "actual": (
                "Terminal modernization."
            ),
            "reference": (
                "Required topic: terminal modernization. That means the response "
                "should stay centered on how an aging passenger terminal is upgraded, "
                "including circulation, customs routing, baggage systems, accessibility "
                "deficiencies, tenant coordination, and project staging during active "
                "operations. Side comments about shuttle contracts or art walls are "
                "still part of the same terminal-modernization topic when they arise "
                "from construction planning. Reviewers expect a passing answer to "
                "recognize that gate assignment disputes, undersized outbound belts, "
                "temporary international corridors, restroom-compliance gaps, snow-"
                "equipment staging, and retail-tenant coordination are all parts of "
                "the same terminal-upgrade problem."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000410"),
        inputs={
            "actual": (
                "Housing affordability policy."
            ),
            "reference": (
                "Required topic: housing affordability policy. For this rubric the "
                "topic covers rent adjustments, tenant protections, restricted "
                "properties, maintenance burdens that drive budgets, and the service "
                "infrastructure needed to keep lower-income residents housed. The "
                "response does not need market theory vocabulary as long as it stays "
                "with rents, tenant impact, and housing-system tradeoffs. Strong "
                "coverage may mention elevator failures, insurance pressure after "
                "kitchen fires, deed restrictions at a senior campus, weatherization "
                "grants, multilingual notices, and the timing of waiting-list "
                "reopenings, because all of those items bear on how affordable housing "
                "is financed, maintained, and administered for residents."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000411"),
        inputs={
            "actual": (
                "Food safety."
            ),
            "reference": (
                "Required topic: food safety. Here that includes contamination "
                "detection, plant sanitation, product withdrawal decisions, regulator "
                "communication, source tracing, and the operational consequences of a "
                "recall. Supplier relations and tourism impact still count as food-"
                "safety context when they flow from a contamination event. Reviewers "
                "expect mention of floor-drain positives, curd-line exposure, "
                "supermarket coordination, environmental swabs, member-farm milk "
                "diversion, and state-inspector involvement, but they still score all "
                "of that as one food-safety topic rather than separate themes."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000412"),
        inputs={
            "actual": (
                "Historic-building preservation."
            ),
            "reference": (
                "Required topic: historic-building preservation. The intended response "
                "should remain focused on protecting an older structure while keeping "
                "collections safe, which means roof repair scope, grant eligibility, "
                "construction staging, conservation risk, and the tension between "
                "public access and preservation priorities. A complete answer might "
                "touch the copper roof, moisture damage, preservation rebates, school-"
                "tour rerouting, reduced café operations, gift-shop delays, and "
                "climate-controlled crate handling for incoming loans, but all of that "
                "still belongs to one preservation topic."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_TOPICS_STRICT_MODE_EXPECTED_TRUE_CASES)
@rue.repeat(2)
async def test_has_topics_strict_mode_expected_true(case: Case) -> None:
    assert await has_topics(**case.input_kwargs)


HAS_TOPICS_STRICT_MODE_EXPECTED_FALSE_CASES: tuple[Case, ...] = (
    Case(
        id=UUID("00000000-0000-0000-0000-000000000413"),
        inputs={
            "actual": (
                "The semiconductor memo moves through power demand, specialty-gas "
                "sourcing, export controls, subsidy exposure, airport cargo "
                "dependencies, rural legislative resistance, environmental objections, "
                "and shortages of industrial electricians. It remains entirely in the "
                "world of advanced manufacturing policy rather than literary theory or "
                "translation studies."
            ),
            "reference": (
                "Required topics: classical poetics, narratology, and modernist "
                "translation theory. A compliant answer would need to discuss "
                "metaphor, meter, focalization, translation choices, and the "
                "interpretive traditions around literary form."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000414"),
        inputs={
            "actual": (
                "The archive relocation brief covers downtown real estate, utilities, "
                "family-paper shelf space, freight-elevator access, public "
                "programming, donor communication, and basement storage arrangements "
                "with the transit museum. It does not become a discussion of mountain "
                "geomorphology, glacial retreat, or snowpack hydrology."
            ),
            "reference": (
                "Required topics: alpine geomorphology, glacier mass balance, and "
                "snowpack hydrology. Reviewers want landform evolution, melt dynamics, "
                "watershed timing, and field measurements in cold mountainous terrain."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000415"),
        inputs={
            "actual": (
                "The airport packet is about gates, conveyor systems, customs routing, "
                "restroom accessibility, construction phasing, and preservation of an "
                "art wall from the commuter wing. It never moves toward pastoral "
                "care, sacramental theology, or comparative liturgy."
            ),
            "reference": (
                "Required topics: sacramental theology, pastoral counseling, and "
                "comparative liturgy. A passing response would need doctrinal "
                "arguments, ritual practice, ministerial guidance, and differences "
                "between liturgical traditions."
            ),
            "strict": True,
        },
    ),
    Case(
        id=UUID("00000000-0000-0000-0000-000000000416"),
        inputs={
            "actual": (
                "The investor update stays with enrollment, endpoints, adult versus "
                "pediatric filing strategy, manufacturing validation, travel freezes, "
                "and conference abstracts. It is not a paper on irrigation rights, "
                "canal apportionment, or riparian doctrine."
            ),
            "reference": (
                "Required topics: riparian doctrine, irrigation districts, and "
                "interstate river compacts. Reviewers want water-right allocation, "
                "canal governance, compact enforcement, and the legal structure of "
                "agricultural water delivery systems."
            ),
            "strict": True,
        },
    ),
)


@rue.iter_cases(*HAS_TOPICS_STRICT_MODE_EXPECTED_FALSE_CASES)
@rue.repeat(2)
async def test_has_topics_strict_mode_expected_false(case: Case) -> None:
    assert not await has_topics(**case.input_kwargs)
