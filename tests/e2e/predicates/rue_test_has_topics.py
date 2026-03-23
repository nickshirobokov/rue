# ruff: noqa: E501, I001
import rue
from rue import Case
from rue.predicates import has_topic

from typing import Any

from pydantic import BaseModel, Field
from textwrap import dedent
from uuid import NAMESPACE_URL, uuid5


class Inputs(BaseModel):
    actual: str = Field(
        description="""
        The actual document. For positive cases, this
        document must be substantively about the
        topic described by the reference string.
        """,
    )
    reference: str = Field(
        description="""
        The reference string. It specifies a single
        topic that should be present as a meaningful
        subject of the actual document.
        """,
    )
    strict: bool = Field(
        description="""
        Strict mode uses the strict evaluation
        variant. Not strict mode uses the default
        evaluation variant.
        """,
    )

    def model_post_init(self, context: Any) -> None:  # noqa: ARG002
        self.actual = dedent(self.actual).strip()
        self.reference = dedent(self.reference).strip()


class Refs(BaseModel):
    expected: bool = Field(
        description="""
        True means the actual document is
        substantively about the reference topic.
        False means the topic is missing or only an
        incidental mention.
        """,
    )


ALL_CASES: list[Case[Inputs, Refs]] = [
    # expected=True, strict=True
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:used_car_listing_topic_very_easy"),
        metadata={
            "slug": "used_car_listing_topic_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Marketplace post for a private-party sale:

        Selling my 2018 Honda Civic EX in silver. The car has 82,140 miles, a clean
        title, and one previous owner. I replaced the front brake pads in January,
        installed a new battery in March, and I still have both original key fobs.
        Registration is paid through November. The only cosmetic issue is a scrape on
        the rear bumper from a parking garage pillar. I am asking $13,400 and can
        meet near the Lake Merritt BART station on weeknights.
        """,
            reference="""
        A document about used car sales, vehicle condition disclosures, ownership
        history, and practical listing details for a compact sedan sold by a private
        owner.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:auth_code_topic_easy"),
        metadata={"slug": "auth_code_topic_easy", "difficulty": "easy"},
        inputs=Inputs(
            actual="""
        # auth/session_manager.py

        def verify_access_token(token: str) -> Claims:
            claims = jwt.decode(token, key=PUBLIC_KEY, algorithms=["RS256"])
            if claims["exp"] < now_utc():
                raise ExpiredToken()
            return claims


        def rotate_refresh_token(session_id: str, presented_token: str) -> SessionState:
            stored = repo.load_refresh_token(session_id)
            if not hash_matches(presented_token, stored.token_hash):
                repo.revoke_session_family(session_id)
                raise RefreshReuseDetected()

            new_token = token_factory.issue_refresh(session_id)
            repo.store_refresh_token(session_id, hash_token(new_token))
            return SessionState(refresh_token=new_token, rotated=True)


        # Access tokens expire after 15 minutes. Refresh-token reuse triggers family
        # revocation so a stolen token cannot continue extending the session.
        """,
            reference="""
        Authentication and session security in a web API, including JWT validation,
        expiration handling, refresh-token rotation, and protection against reused
        session credentials.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(NAMESPACE_URL, f"{__name__}:auth_code_topic_medium"),
        metadata={"slug": "auth_code_topic_medium", "difficulty": "medium"},
        inputs=Inputs(
            actual="""
        # auth/session_manager.py
        # bridge copy, comments still rough

        def verify_access_token(token: str) -> Claims:
            claims = jwt.decode(token, key=PUBLIC_KEY, algorithms=["RS256"])
            if claims["exp"] < now_utc():
                raise ExpiredToken()
            return claims


        def rotate_refresh_token(session_id: str, presented_token: str) -> SessionState:
            stored = repo.load_refresh_token(session_id)
            if not hash_matches(presented_token, stored.token_hash):
                repo.revoke_session_family(session_id)
                audit.log("refresh reuse for %s" % session_id)
                raise RefreshReuseDetected()

            new_token = token_factory.issue_refresh(session_id)
            repo.store_refresh_token(session_id, hash_token(new_token))
            return SessionState(refresh_token=new_token, rotated=True)


        # ops scraps:
        # - access tokens expire after 15 min.
        # - refresh-token reuse revokes the whole family, so a stolen token
        #   cannot keep extending the session.
        # - one support ticket asked whether copying an old browser cookie could
        #   survive reuse detection. it could not.
        # - Q4 laptop budgeting is still open for the platform team.
        """,
            reference="""
        Authentication and session security in a web API, including JWT
        validation, expiration handling, refresh-token rotation, reuse detection,
        session revocation, and protection against stolen credentials.
        """,
            strict=True,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:incidental_car_mention_not_topic_very_easy",
        ),
        metadata={
            "slug": "incidental_car_mention_not_topic_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Please review the attached lease before tomorrow's signing call. The only
        open issues are the cap on annual CAM increases, the wording around HVAC
        repair response times, and whether the landlord will accept electronic notice
        for default cures. I can drive the paper copy over in my car if legal wants
        original signatures on file before noon, but otherwise I would rather keep
        the process in DocuSign.
        """,
            reference="""
        Used car sales, vehicle condition, mileage, title status, and seller
        disclosures for consumer auto listings.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:fleeting_postgres_mention_not_topic_easy",
        ),
        metadata={
            "slug": "fleeting_postgres_mention_not_topic_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Board update:

        The company plans to hire four more account executives in the Midwest,
        tighten discount approval thresholds, and defer the warehouse expansion
        until Q1. Marketing asked for another $180,000 for partner events after the
        fall campaign underperformed. Engineering has one line item to finish a
        routine Postgres index rebuild on the analytics cluster next week, but the
        larger discussion in this memo is headcount, pipeline coverage, and cash
        runway through the first half of next year.
        """,
            reference="""
        Database performance tuning in Postgres, especially query latency, indexing
        strategy, planner behavior, and optimization of slow analytical workloads.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:fleeting_postgres_mention_not_topic_medium",
        ),
        metadata={
            "slug": "fleeting_postgres_mention_not_topic_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Draft for Monday's board packet:

        Pipeline coverage in the Southeast is still light, so sales wants two more
        account executives and a higher travel budget before kickoff season.
        Finance pushed back on the warehouse lease amendment, marketing wants to
        move another $240,000 into partner events, and people ops is delaying the
        recruiter search until the comp bands settle.

        Appendix: operating items
        the analytics team will run a routine Postgres index rebuild next week,
        refresh planner stats, and vacuum two reporting tables after the month-end
        load.

        The remaining pages cover churn by segment, renewal assumptions, channel
        mix, and the revised Midwest ramp model for the second half.
        """,
            reference="""
        Database performance tuning in Postgres, especially query latency, indexing
        strategy, planner behavior, and optimization of slow analytical workloads.
        """,
            strict=False,
        ),
        references=Refs(expected=False),
    ),
    # expected=True, strict=False
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:multi_topic_database_performance_very_easy",
        ),
        metadata={
            "slug": "multi_topic_database_performance_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Engineering weekly update:

        We cut the slowest dashboard query from 4.8 seconds to 620 milliseconds by
        replacing two broad indexes with a narrower composite index and by dropping a
        planner hint that had been forcing a bad join order. Vacuum frequency on the
        reporting tables also had to increase because dead tuples were bloating the
        index pages after every nightly import. Separately, we opened two backend
        roles for the payments team, but the main focus of this update is still the
        Postgres work needed to keep analytical traffic stable.
        """,
            reference="""
        Database performance in Postgres for slow analytical queries, including index
        design, planner behavior, table bloat, and query-latency reduction.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:remote_work_topic_even_when_opposed_easy",
        ),
        metadata={
            "slug": "remote_work_topic_even_when_opposed_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Opinion draft for the leadership blog:

        I do not think a fully remote company is the right model for our next stage.
        The argument is not that people are lazy at home; it is that junior staff
        learn slower when every question becomes another scheduled call, and product
        decisions lose speed when design, support, and engineering share less
        day-to-day context. Remote work still has advantages for focused tasks and
        for distributed hiring, but this piece is explicitly about the tradeoffs of
        remote collaboration, hybrid expectations, and how team rituals change when
        most work happens away from a shared office.
        """,
            reference="""
        Remote work policy and distributed collaboration, including arguments for or
        against remote teams, hybrid arrangements, and the way distance changes
        communication and coordination.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:remote_work_topic_even_when_opposed_medium",
        ),
        metadata={
            "slug": "remote_work_topic_even_when_opposed_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Leadership blog draft v3:

        I still do not buy the claim that every company improves the moment it
        goes fully remote. People can do focused work at home; the harder question
        is what happens to onboarding, shared context, and decision speed when
        most collaboration moves to scheduled calls and chat threads across time
        zones.

        Hybrid setups add their own mess. Teams end up negotiating who has to be
        in-person for planning, who gets left out of hallway decisions, and how
        managers are supposed to coach new hires they rarely see. Those tradeoffs
        are why I think a remote-first model is wrong for our next stage.
        """,
            reference="""
        Remote work policy and distributed collaboration, including arguments for
        or against remote teams, hybrid arrangements, and the way distance changes
        communication and coordination.
        """,
            strict=False,
        ),
        references=Refs(expected=True),
    ),
    # expected=False, strict=True
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:financial_index_not_database_index_very_easy",
        ),
        metadata={
            "slug": "financial_index_not_database_index_very_easy",
            "difficulty": "very_easy",
        },
        inputs=Inputs(
            actual="""
        Market commentary:

        The equal-weight index outperformed the headline benchmark for a second week
        as energy and regional banks rallied into month-end. Several managers said
        investors were shifting toward smaller names after the mega-cap trade looked
        crowded. We are still indexing our client note archive by sector and quarter,
        but the substance of this piece is market breadth, valuation rotation, and
        fund flows rather than software performance.
        """,
            reference="""
        Postgres indexing and query latency in analytics systems, especially how
        database indexes affect execution plans and performance under reporting
        workloads.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:dog_friendly_lease_not_adoption_topic_easy",
        ),
        metadata={
            "slug": "dog_friendly_lease_not_adoption_topic_easy",
            "difficulty": "easy",
        },
        inputs=Inputs(
            actual="""
        Leasing brochure for Harbor Yards:

        The building allows up to two dogs per apartment, includes a wash station on
        level one, and has a fenced relief area next to the east parking structure.
        Residents are responsible for vaccination records and waste disposal, and the
        leasing office can provide a list of nearby groomers and veterinarians. The
        brochure is about amenities for current tenants with pets, not about shelter
        operations, foster placement, or finding permanent homes for adoptable dogs.
        """,
            reference="""
        Pet adoption and shelter intake operations for dogs, including foster
        placement, adoption screening, and management of dogs entering or leaving a
        rescue organization.
        """,
            strict=True,
        ),
        references=Refs(expected=False),
    ),
    Case[Inputs, Refs](
        id=uuid5(
            NAMESPACE_URL,
            f"{__name__}:dog_friendly_lease_not_adoption_topic_medium",
        ),
        metadata={
            "slug": "dog_friendly_lease_not_adoption_topic_medium",
            "difficulty": "medium",
        },
        inputs=Inputs(
            actual="""
        Harbor Yards leasing FAQ:

        Dogs are welcome in up to two-pet households, pending vaccination records
        and the usual weight-limit form. Residents can use the wash station on
        level one, the fenced relief run by the east garage, and the after-hours
        hose bib behind building C. The office keeps a handout of nearby groomers,
        emergency vets, dog walkers, and the weekend vaccination clinic at the
        shopping center.

        A few applicants have asked whether exceptions exist for dogs coming out of
        foster homes or informal rescues. Leasing handles that the same way it
        handles any other pet application: records, deposit, leash rules, waste
        disposal, and building access after move-in.
        """,
            reference="""
        Pet adoption and shelter intake operations for dogs, including foster
        placement, adoption screening, and management of dogs entering or leaving a
        rescue organization.
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
async def test_has_topic_strict_false_expected_true(case: Case[Inputs, Refs]):
    assert await has_topic(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and not case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topic_strict_false_expected_false(case: Case[Inputs, Refs]):
    assert not await has_topic(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topic_strict_true_expected_true(case: Case[Inputs, Refs]):
    assert await has_topic(**case.input_kwargs)


@rue.iter_cases(
    *[
        case
        for case in ALL_CASES
        if not case.references.expected and case.inputs.strict
    ]
)
@rue.repeat(2)
async def test_has_topic_strict_true_expected_false(case: Case[Inputs, Refs]):
    assert not await has_topic(**case.input_kwargs)
