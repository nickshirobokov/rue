"""LLM predicate for unsupported facts."""

from rue.predicates.clients import LLMPredicate

# Prompts

HAS_UNSUPPORTED_FACTS_NORMAL_PROMPT = """You are executing the boolean predicate has_unsupported_facts(actual, reference, strict=False).

This prompt is a program specification, not a conversation. Evaluate whether the document named
actual contains any factual claim that is not supported by the document named reference under
open-world semantics. The output must follow the response schema exactly. Reason internally. If
the output schema requests an explanation, provide a short factual justification and nothing else.

Semantic target:
- Return True if and only if there exists at least one fact in actual that reference does not
  support.
- This predicate is directional. It detects extra or unbacked factual content in actual relative
  to reference.
- Unsupported includes benign additions, over-claims, and contradictory additions.
- Unsupported does not require conflict.
- If every factual claim in actual is supported by reference, return False.

Document model:
- Treat both inputs as arbitrary documents, not as clean fact lists.
- Inputs may be prose, conversations, logs, listings, contracts, recipes, JSON, YAML, XML,
  program code, comments, tests, config, markdown, or mixed text.
- Facts may be explicit, structural, distributed across multiple spans, or derivable through short
  text-anchored reasoning.
- Ignore purely non-factual style or tone content unless it conveys a factual proposition.

Fact model:
- A fact is a proposition about the world, an entity, an event, a relation, a quantity, a time,
  a location, a cause, or an evaluative property that can be compared for support or conflict.
- Keep relevant qualifiers. Do not erase negation, time, quantity, modality, exclusivity,
  causality, scope, identity, comparison, or conditions.
- Different wording can still express the same fact. Do not require lexical overlap.

Format-aware extraction examples:
- Craigslist listing: "2018 Honda Civic, 82k miles, one owner, clean title, needs brake pads
  soon" contains several distinct facts, each of which must be checked for support independently.
- Recipe text: "Add 2 eggs, whisk with sugar, bake at 350F for 25 minutes" contains multiple
  factual claims about ingredients, temperature, and duration.
- Code or config: `MAX_RETRIES = 3` may assert the fact "maximum retries is 3" when the text is
  being used as declarative configuration.

Support rules for open-world evaluation:
- Determine whether reference supports each factual claim found in actual.
- Support may come from direct assertion.
- Support may come from paraphrase or equivalent reformulation.
- Support may come from structural interpretation of declarative content such as JSON fields,
  constants, config values, schema fields, comments, tests, or examples.
- Support may come from coreference and alias resolution.
- Support may come from short compositional transfer across explicit textual connections.
- Support may come from discourse-act-derived evidence when the text conveys factual identity or
  content.
- Support may come from summarization, abstraction, or reasonable completion under
  underspecification when the compared fact is strongly grounded and contradiction-free.
- A more specific reference fact can support a shorter or broader actual summary when the summary
  only drops detail rather than adding a new commitment.
- Same-event reflective or evaluative summaries may be supported by a more concrete narrative when
  they are clearly grounded in that event and introduce no incompatible detail.
- Open-world mode is permissive but must remain text-anchored. Do not guess ungrounded facts.
- Bounded transfer matters. "Bob likes apples" plus "I like same fruits as Bob" may support
  "I like apples", but it does not support "I like pears" because pears are not grounded in the
  text.

Predicate-specific boundaries:
- This predicate asks whether actual says anything factual that reference does not support.
- It does not ask whether reference contains additional facts missing from actual.
- A compatible subset is not unsupported. Example: actual "Agent's name is Roger." and reference
  "Agent's name is Roger and he works in support." must return False.
- A compatible superset is unsupported. Example: actual "Agent's name is Roger and he works in
  support." and reference "Agent's name is Roger." must return True.
- A contradictory addition is unsupported. Example: actual "Agent's name is Mike." and reference
  "Agent's name is Roger." must return True.
- Coverage plus contradiction is still unsupported. Example: actual "Agent's name is Roger.
  Agent's name is Mike." and reference "Agent's name is Roger." must return True because the Mike
  claim is not supported by reference.
- If actual contains one supported fact and one unsupported fact, return True. A single unsupported
  fact is sufficient.

Required open-world examples:
- actual: "Roger is the agent and lives in SF"
  reference: "Roger is the agent"
  verdict: True because "lives in SF" is unsupported even though it is not conflicting
- actual: "Agent introduced himself as Roger"
  reference: "Agent's name is Roger"
  verdict: True because the name fact is supported, but actual also asserts an introduction event
  that reference does not mention. A single unsupported fact is sufficient.
- actual: "we had so much fun yesterday"
  reference: "thanks for the dinner yesterday, that was amazing"
  open-world verdict: False because the event may reasonably align and the actual fact need not be
  treated as unsupported
- actual: "The apartment includes one covered parking stall."
  reference: "The apartment includes one covered parking stall in the south garage."
  open-world verdict: False because the broader summary is supported by the more specific
  reference fact
- actual: "The team finally relaxed after the migration."
  reference: "After the migration, the team stayed out for a long dinner, kept laughing, and
  looked relaxed for the first time all week."
  open-world verdict: False because the actual sentence is a grounded same-event summary of the
  reference
- actual: "Apple lost $1B because iPhone 17 Pro has bad camera and some other factors"
  reference: "Bad iPhone camera and bad speaker led to poor Apple returns"
  open-world verdict: False because the actual content can be supported by a permissive grounded
  reading of the reference and aligned abstractions

Empty-fact behavior:
- If actual contains no extractable facts, return False.
- If reference contains no extractable facts and actual contains at least one fact, return True.
- If both documents contain no extractable facts, return False.

Common mistakes to avoid:
- Do not return False just because one actual fact is supported. One unsupported actual fact is
  enough for True.
- Do not confuse unsupported with conflicting. Unsupported facts may be compatible additions.
- Do not require lexical overlap when testing support.
- Do not treat extra detail present only in reference as a reason to mark a shorter actual summary
  unsupported.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of actual.
3. Extract or derive the fact graph of reference.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Before declaring an actual fact unsupported, check whether it is just a shorter summary of a
   more specific reference fact grounded in the same entities, event, time, or attribute.
6. Internally enumerate every actual fact and ask whether reference supports it under open-world
   rules.
7. Return True as soon as one actual fact is unsupported.
8. Return False only if every actual fact is supported or actual contains no facts.

Final reminder:
- Return True as soon as any one actual fact lacks support in reference, even if all other actual
  facts are fully supported.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, name the unsupported actual fact or state that all actual
  facts were supported.
"""

HAS_UNSUPPORTED_FACTS_STRICT_PROMPT = """You are executing the boolean predicate has_unsupported_facts(actual, reference, strict=True).

This prompt is a program specification, not a conversation. Evaluate whether the document named
actual contains any factual claim that is not supported by the document named reference under
closed-world semantics. The output must follow the response schema exactly. Reason internally. If
the output schema requests an explanation, provide a short factual justification and nothing else.

Semantic target:
- Return True if and only if there exists at least one fact in actual that reference does not
  support.
- This predicate is directional from actual to reference.
- Unsupported includes harmless additions, speculative additions, and contradictory additions.
- Unsupported does not require conflict.

Closed-world rules:
- Closed-world evaluation is conservative and text-bounded.
- Only explicit content and near-paraphrase count by default.
- Anchored semantic consequence is allowed.
- Free completion of missing detail is not allowed.
- Unfilled placeholders are not freely instantiated.
- Omitted qualifiers are not assumed.
- Vague descriptions are not promoted to precise claims without strong textual licensing.

Document model:
- Treat actual and reference as arbitrary documents.
- Facts may appear in prose, structure, code, config, comments, tests, logs, contracts, listings,
  recipes, or mixed text.
- Facts may be distributed across multiple spans, but support must remain strongly anchored.

Fact model:
- A fact is a supportable or contradictable proposition.
- Preserve qualifiers such as negation, time, quantity, modality, exclusivity, causality, scope,
  identity, comparison, and conditions.
- Near-paraphrase is acceptable; lexical overlap is not required.

Format-aware extraction examples:
- Craigslist listing: extract each structured attribute as a separate factual claim before testing
  support.
- Recipe text: extract ingredient, temperature, and duration claims separately.
- Code or config: `MAX_RETRIES = 3` may assert "maximum retries is 3" when the text is declarative.

Allowed support in closed world:
- Direct assertion.
- Near-paraphrase.
- Structural extraction from declarative data or code when clearly justified.
- Clear coreference.
- Short explicit compositional transfer.
- Identity conveyed by discourse acts such as self-introduction.
- A more specific reference fact may support a broader actual summary when the summary stays
  tightly anchored and only omits detail rather than adding new unsupported specifics.
- Bounded transfer matters. "Bob likes apples. I like same fruits as Bob." may support
  "I like apples", but it does not support "I like pears" because pears are not grounded anywhere
  in the text.

Required closed-world examples:
- actual: "Agent's name is Roger and he works in support."
  reference: "Agent's name is Roger."
  verdict: True
- actual: "Agent's name is Roger."
  reference: "Agent's name is Roger and he works in support."
  verdict: False
- actual: "we had so much fun yesterday"
  reference: "thanks for the dinner yesterday, that was amazing"
  closed-world verdict: True because dinner is not anchored explicitly enough
- actual: "Apple lost $1B because iPhone 17 Pro has bad camera and some other factors"
  reference: "Bad iPhone camera and bad speaker led to poor Apple returns"
  closed-world verdict: True because speaker and the precise $1B loss are not sufficiently
  supported in this conservative mode
- actual: "Bob likes apples. I like same fruits as Bob."
  reference: "I like apples."
  closed-world verdict: True because actual also asserts "Bob likes apples," which reference does
  not support
- actual: "Agent introduced himself as Roger"
  reference: "Agent's name is Roger"
  closed-world verdict: True because reference supports the name fact, but actual also asserts an
  introduction event that reference does not support. A single unsupported fact is sufficient.
- actual: "Ava will start on the billing queue this week."
  reference: "Ava said her first two shifts this week would be shadowing the billing queue."
  closed-world verdict: False because the broader start-on-queue-this-week summary is strongly
  anchored by the more specific reference statement

Empty-fact behavior:
- If actual contains no extractable facts, return False.
- If reference contains no extractable facts and actual contains at least one fact, return True.
- If both documents contain no extractable facts, return False.

Common mistakes to avoid:
- Do not return False just because some actual facts are supported.
- Do not confuse lack of support with contradiction.
- Do not invent support for ungrounded details.
- Do not mark an actual summary as unsupported merely because reference states the same fact with
  more detail.
- Do not mistake a more specific onboarding, scheduling, assignment, or location detail in
  reference for a contradiction of a broader actual summary that stays within that same anchored
  fact.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of actual.
3. Extract or derive the fact graph of reference.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Before declaring an actual fact unsupported, check whether it is merely a broader summary of a
   more specific reference fact about the same anchored event, role, assignment, time, or
   attribute.
6. Internally enumerate each actual fact and compare it against reference using closed-world
   support rules.
7. Return True as soon as one actual fact is unsupported.
8. Return False only if every actual fact is supported or actual contains no facts.

Final reminder:
- Return True as soon as one actual fact is not supported by reference, even if many other actual
  facts are supported.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, identify the unsupported actual fact or state that no
  unsupported actual facts were found.
"""

HAS_UNSUPPORTED_FACTS_TASK_TEMPLATE = """Evaluate the predicate has_unsupported_facts for the two documents below.

Actual document:
<actual>
{actual}
</actual>

Reference document:
<reference>
{reference}
</reference>
"""


# Predicate

predicate_instance = LLMPredicate(
    predicate_name="has_unsupported_facts",
    normal_prompt=HAS_UNSUPPORTED_FACTS_NORMAL_PROMPT,
    strict_prompt=HAS_UNSUPPORTED_FACTS_STRICT_PROMPT,
    task_template=HAS_UNSUPPORTED_FACTS_TASK_TEMPLATE,
)

has_unsupported_facts = predicate_instance.build_predicate()

__all__ = ["has_unsupported_facts"]
