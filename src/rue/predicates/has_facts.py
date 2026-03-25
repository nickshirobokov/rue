"""LLM predicate for required facts."""

from rue.predicates.clients import LLMPredicate


HAS_FACTS_NORMAL_PROMPT = """You are executing the boolean predicate has_facts(actual, reference, strict=False).

This prompt is a program specification, not a conversation. Evaluate factual coverage from the
document named actual to the document named reference under open-world semantics. The output
must follow the response schema exactly. Reason internally. If the output schema requests an
explanation, provide a short factual justification and nothing else.

Semantic target:
- Return True if and only if every fact supported or asserted by reference is also supported by
  actual.
- This predicate is directional. It is coverage from reference to actual.
- This predicate does not ask whether actual has extra facts.
- This predicate does not ask whether actual is conflict-free overall.
- Coverage and contradiction may coexist. If actual supports the reference facts and also states
  incompatible extra facts, the verdict is still True for this predicate.

Document model:
- Treat actual and reference as arbitrary documents, not as clean bullet lists.
- Documents may be prose, chat logs, contracts, recipes, Craigslist listings, JSON, YAML, XML,
  markdown, code, comments, tests, config, forum threads, or mixed-format text.
- Documents may contain zero facts, one fact, many facts, noise, redundancy, or internal
  contradiction.
- Facts may be expressed directly, structurally, across multiple spans, or through short
  text-anchored reasoning chains.

Fact model:
- A fact is a proposition about the world, an entity, an event, a relation, a quantity, a time,
  a location, a cause, or an evaluative property that can be compared for support or conflict.
- Preserve meaning-bearing qualifiers. Do not silently drop negation, time, quantity, modality,
  certainty, exclusivity, causality, scope, identity, comparison, or conditions.
- "Apple lost money", "Apple lost $1B", "Apple may have lost $1B", and "Apple lost $1B only
  because of camera issues" are different facts.
- Different wording can still express the same fact. Do not require lexical overlap.

Format-aware extraction examples:
- Craigslist listing: "2018 Honda Civic, 82k miles, one owner, clean title, needs brake pads
  soon" supports facts such as: the car is a 2018 Honda Civic; mileage is 82,000; ownership count
  is one; title is clean; brake pads need replacement soon.
- Recipe text: "Add 2 eggs, whisk with sugar, bake at 350F for 25 minutes" supports facts such as:
  the recipe uses 2 eggs; baking temperature is 350F; baking duration is 25 minutes.
- Code or config: `MAX_RETRIES = 3` may support the fact "maximum retries is 3" when the text is
  functioning as declarative configuration rather than unrelated arbitrary code.

Support rules for open-world evaluation:
- Support is directional. Determine whether actual supports each fact in reference.
- Support may come from direct assertion.
- Support may come from paraphrase or equivalent reformulation.
- Support may come from structural interpretation of data or code when the text functions as
  declarative content. Example: JSON fields, constants, config values, schema fields, comments,
  tests, and examples may express facts.
- Support may come from coreference and alias resolution.
- Support may come from short compositional transfer across explicit connections in the text.
  Example: "Bob likes apples" plus "I like same fruits as Bob" supports "I like apples."
- Support may come from discourse-act-derived evidence when the text conveys factual identity or
  content. Example: "Agent introduced himself as Roger" supports "Agent's name is Roger."
- Support may come from summarization, abstraction, or reasonable completion under
  underspecification when the completion is strongly grounded in the document and no contradiction
  blocks it.
- Open-world mode is permissive. Broad and specific descriptions may align if the specific
  interpretation is a natural fit for the text.
- Open-world mode may instantiate underspecified remainder phrases when the compared fact is a
  reasonable grounded completion.
- Open-world mode may align event descriptions more flexibly when the text strongly suggests the
  same event or situation.
- Open-world mode must remain grounded. Do not invent facts that are not anchored in the text.
- Support transfer is bounded. "Bob likes apples" plus "I like same fruits as Bob" supports
  "I like apples", but it does not support "I like pears" because pears are never grounded in the
  text.

Boundaries:
- Unsupported is not the same as conflicting, and conflicting is not the same as uncovered.
- Do not penalize actual for extra supported facts.
- Do not penalize actual for extra unsupported facts.
- Do not set this predicate to False merely because actual contains contradictions elsewhere.
- Set this predicate to False only when at least one fact from reference is not supported by
  actual under open-world rules.

Required examples:
- actual: "Agent's name is Roger and he works in support."
  reference: "Agent's name is Roger."
  verdict: True
- actual: "Agent's name is Roger."
  reference: "Agent's name is Roger and he works in support."
  verdict: False
- actual: "Agent's name is Roger. Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: True
- actual: "we had so much fun yesterday"
  reference: "thanks for the dinner yesterday, that was amazing"
  open-world verdict: True because the same positive event may reasonably be interpreted as the
  dinner event
- actual: "Apple lost $1B because iPhone 17 Pro has bad camera and some other factors"
  reference: "Bad iPhone camera and bad speaker led to poor Apple returns"
  open-world verdict: True because speaker can be a grounded completion of the remainder phrase
  and $1B loss can support poor returns in this permissive mode
- actual: "Bob likes apples. I like same fruits as Bob."
  reference: "I like apples."
  verdict: True
- actual: "Agent introduced himself as Roger"
  reference: "Agent's name is Roger"
  verdict: True

Empty-fact behavior:
- If reference contains no extractable facts, return True.
- If reference contains facts and actual contains no extractable facts, return False.
- If both documents contain no extractable facts, return True.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of reference.
3. Extract or derive the fact graph of actual.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Internally enumerate each reference fact and determine whether actual supports it under the
   open-world rules above.
6. Return True only if every reference fact is supported.
7. Otherwise return False.

Final reminder:
- Return True as long as every reference fact is supported by actual, even if actual also contains
  extra unsupported facts or extra conflicting facts elsewhere.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, state which reference fact was unsupported or state that
  all reference facts were supported.
"""

HAS_FACTS_STRICT_PROMPT = """You are executing the boolean predicate has_facts(actual, reference, strict=True).

This prompt is a program specification, not a conversation. Evaluate factual coverage from the
document named actual to the document named reference under closed-world semantics. The output
must follow the response schema exactly. Reason internally. If the output schema requests an
explanation, provide a short factual justification and nothing else.

Semantic target:
- Return True if and only if every fact supported or asserted by reference is also supported by
  actual.
- This predicate is directional. It checks coverage from reference to actual.
- Ignore whether actual contains extra facts unless those extras change the interpretation so a
  reference fact is no longer supported.
- Ignore whether actual contains contradictions elsewhere. Coverage and contradiction may coexist.

Closed-world rules:
- Closed-world evaluation is conservative, text-bounded, and comparatively literal.
- Only explicit content and near-paraphrase count by default.
- Bounded inference is allowed only when the connection is strongly anchored in the text.
- Unfilled placeholders are not freely instantiated.
- Omitted qualifiers are not assumed.
- Vague descriptions are not freely mapped to precise values.
- Broad commonsense completion is minimized.
- Closed world does not forbid reasoning. It allows anchored semantic consequence.

Document model:
- Treat actual and reference as arbitrary documents, not as clean fact lists.
- Documents may contain prose, structured data, code, comments, transcripts, logs, contracts,
  recipes, listings, or mixed material.
- Facts may be explicit, distributed across spans, expressed structurally, or recoverable through
  short strongly anchored reasoning chains.

Fact model:
- A fact is a proposition that can be compared for support or conflict.
- Keep relevant qualifiers intact: negation, time, quantity, modality, exclusivity, causality,
  scope, identity, comparison, and conditions.
- Do not collapse materially different claims into one fact.
- Do not require exact wording when a near-paraphrase or explicit semantic consequence preserves
  the same proposition.

Format-aware extraction examples:
- Craigslist listing: "2018 Honda Civic, 82k miles, one owner, clean title, needs brake pads
  soon" supports facts such as model year and make, mileage, owner count, title status, and brake
  condition.
- Recipe text: "Add 2 eggs, whisk with sugar, bake at 350F for 25 minutes" supports facts such as
  egg count, baking temperature, and baking duration.
- Code or config: `MAX_RETRIES = 3` may support "maximum retries is 3" when the text is acting as
  declarative configuration.

Allowed support in closed world:
- Direct assertion.
- Near-paraphrase and equivalent reformulation.
- Structural extraction from declarative JSON, config, constants, schema, comments, tests, or
  examples when that interpretation is textually justified.
- Coreference resolution when clearly anchored.
- Short compositional transfer when explicitly licensed by the text.
- Discourse-act-derived support when the discourse act explicitly conveys the factual content.
- Support transfer is bounded. "Bob likes apples. I like same fruits as Bob." supports
  "I like apples", but it does not support "I like pears" because pears are not grounded anywhere
  in the text.

Required closed-world examples:
- "Bob likes apples. I like same fruits as Bob." supports "I like apples."
- "Agent introduced himself as Roger" supports "Agent's name is Roger."
- "we had so much fun yesterday" does not support "thanks for the dinner yesterday, that was
  amazing"
- "Apple had poor returns" does not support "Apple lost $1B"
- "Camera and some other factors caused the loss" does not support "speaker issues caused the
  loss"

Boundaries:
- Do not penalize actual for extra supported facts.
- Do not penalize actual for extra unsupported facts.
- Do not set this predicate to False merely because actual also states a conflicting extra fact.
- Example: actual "Agent's name is Roger. Agent's name is Mike." and reference "Agent's name is
  Roger." must return True for this predicate because the reference fact is covered.
- Set this predicate to False only when at least one fact from reference lacks sufficiently
  anchored support in actual.

Empty-fact behavior:
- If reference contains no extractable facts, return True.
- If reference contains facts and actual contains no extractable facts, return False.
- If both documents contain no extractable facts, return True.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of reference.
3. Extract or derive the fact graph of actual.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Internally enumerate each reference fact and compare it against actual using closed-world
   support rules.
6. Return True only if every reference fact is supported.
7. Otherwise return False.

Final reminder:
- Return True as long as every reference fact is supported by actual. Extra content in actual,
  including unsupported or conflicting extra content, does not by itself make this predicate
  False.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, identify the missing reference coverage or state that all
  reference facts were covered.
"""

HAS_FACTS_TASK_TEMPLATE = """Evaluate the predicate has_facts for the two documents below.

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
    predicate_name="has_facts",
    normal_prompt=HAS_FACTS_NORMAL_PROMPT,
    strict_prompt=HAS_FACTS_STRICT_PROMPT,
    task_template=HAS_FACTS_TASK_TEMPLATE,
)

has_facts = predicate_instance.build_predicate()

__all__ = ["has_facts"]
