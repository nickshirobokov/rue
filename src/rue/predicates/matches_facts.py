"""LLM predicate for full fact matching."""

from .clients import LLMPredicate


MATCHES_FACTS_NORMAL_PROMPT = """You are executing the boolean predicate matches_facts(actual, reference, strict=False).

This prompt is a program specification, not a conversation. Evaluate factual equivalence between
the documents named actual and reference under open-world semantics. The output must follow the
response schema exactly. Reason internally. If the output schema requests an explanation, provide
a short factual justification and nothing else.

Semantic target:
- Return True if and only if the two documents are factually equivalent under the selected world
  assumption.
- Operationally, this requires all three conditions:
  1. Every fact in reference is supported by actual.
  2. Every fact in actual is supported by reference.
  3. No fact in actual conflicts with any fact in reference.
- This is the strongest fact predicate. It is not semantic similarity, topical overlap, or same
  gist. It is factual equivalence.

Document model:
- Treat actual and reference as arbitrary documents, not as clean fact lists.
- Inputs may be prose, conversations, logs, listings, contracts, recipes, JSON, YAML, XML,
  markdown, program code, comments, tests, config, or mixed-format text.
- Facts may be explicit, structural, distributed across multiple spans, or derivable through short
  text-anchored reasoning chains.

Fact model:
- A fact is a proposition about the world, an entity, an event, a relation, a quantity, a time,
  a location, a cause, or an evaluative property that can be compared for support or conflict.
- Preserve qualifiers. Negation, time, quantity, modality, exclusivity, causality, scope,
  identity, comparison, and conditions are part of the fact.
- Do not require lexical overlap. Paraphrases and equivalent reformulations may express the same
  fact.

Format-aware extraction examples:
- Craigslist listing: "2018 Honda Civic, 82k miles, one owner, clean title, needs brake pads
  soon" yields multiple independent facts about the car and its condition.
- Recipe text: "Add 2 eggs, whisk with sugar, bake at 350F for 25 minutes" yields independent
  ingredient and procedure facts such as egg count, temperature, and duration.
- Code or config: `MAX_RETRIES = 3` may express "maximum retries is 3" when the text is acting as
  declarative configuration.

Open-world support rules:
- Support may come from direct assertion, paraphrase, structural extraction, coreference, alias
  resolution, short compositional transfer, discourse-act-derived evidence, summarization, or
  grounded completion under underspecification.
- Open-world mode is permissive. Broad and specific descriptions may align when the specific
  interpretation is a natural grounded fit.
- Open-world mode may instantiate underspecified remainder phrases when the compared fact is a
  reasonable grounded completion.
- Open-world mode may align same-event descriptions more flexibly.
- Open-world mode must remain text-anchored. Do not invent ungrounded facts.
- Bounded transfer matters. "Bob likes apples. I like same fruits as Bob." may support
  "I like apples", but it does not support "I like pears" because pears are never grounded in the
  text.

Conflict rules:
- Conflict exists when two facts cannot both hold under a coherent interpretation of the same
  entities, events, times, scopes, and qualifiers.
- Conflict is stronger than non-support.
- Unsupported but compatible content makes this predicate False even without conflict because
  equivalence requires two-way support.

Predicate-specific consequences:
- A compatible superset is not a match.
- A compatible subset is not a match.
- A contradiction is not a match.
- Coverage plus contradiction is not a match.
- Exact equivalence, paraphrastic equivalence, and grounded bidirectional support without conflict
  are matches.

Required open-world examples:
- actual: "Agent's name is Roger."
  reference: "Agent's name is Roger."
  verdict: True
- actual: "Agent's name is Roger and he works in support."
  reference: "Agent's name is Roger."
  verdict: False because actual has an extra unsupported fact
- actual: "Agent's name is Roger."
  reference: "Agent's name is Roger and he works in support."
  verdict: False because actual lacks a reference fact
- actual: "Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: False because there is conflict and missing support
- actual: "Agent's name is Roger. Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: False because there is conflict and unsupported extra content
- actual: "we had so much fun yesterday"
  reference: "thanks for the dinner yesterday, that was amazing"
  open-world verdict: True because the event may reasonably align in both directions
- actual: "Apple lost $1B because iPhone 17 Pro has bad camera and some other factors"
  reference: "Bad iPhone camera and bad speaker led to poor Apple returns"
  open-world verdict: True because open-world support allows the grounded abstraction and
  completion used by the spec
- actual: "Bob likes apples. I like same fruits as Bob."
  reference: "I like apples."
  verdict: False because actual includes the extra fact "Bob likes apples," which reference does
  not support
- actual: "Agent introduced himself as Roger"
  reference: "Agent's name is Roger"
  verdict: False because the introduction event is extra factual content not supported by
  reference

Empty-fact behavior:
- If both documents contain no extractable facts, return True.
- If reference contains no extractable facts and actual contains at least one fact, return False.
- If actual contains no extractable facts and reference contains at least one fact, return False.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of actual.
3. Extract or derive the fact graph of reference.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Internally enumerate the reference facts, actual facts, support links, and conflict links.
6. Test whether every reference fact is supported by actual under open-world rules.
7. Test whether every actual fact is supported by reference under open-world rules.
8. Test whether any actual fact conflicts with any reference fact.
9. Return True only if the two support checks succeed and the conflict check fails.
10. Otherwise return False.

Final reminder:
- This predicate is strict factual equivalence. One uncovered reference fact, one extra unsupported
  actual fact, or one conflict is enough to make the result False.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, state which of the three conditions failed, or state that
  two-way support held with no conflict.
"""

MATCHES_FACTS_STRICT_PROMPT = """You are executing the boolean predicate matches_facts(actual, reference, strict=True).

This prompt is a program specification, not a conversation. Evaluate factual equivalence between
the documents named actual and reference under closed-world semantics. The output must follow the
response schema exactly. Reason internally. If the output schema requests an explanation, provide
a short factual justification and nothing else.

Semantic target:
- Return True if and only if the two documents are factually equivalent under conservative
  closed-world evaluation.
- Operationally, require all three conditions:
  1. Every fact in reference is supported by actual.
  2. Every fact in actual is supported by reference.
  3. No actual fact conflicts with any reference fact.

Closed-world rules:
- Closed-world evaluation is conservative, text-bounded, and comparatively literal.
- Only explicit content and near-paraphrase count by default.
- Anchored semantic consequence is allowed.
- Unfilled placeholders are not freely instantiated.
- Omitted qualifiers are not assumed.
- Vague descriptions are not freely upgraded to precise claims.
- Broad commonsense completion is minimized.
- Bounded transfer matters. "Bob likes apples. I like same fruits as Bob." may support
  "I like apples", but it does not support "I like pears" because pears are not grounded anywhere
  in the text.

Document model:
- Treat inputs as arbitrary documents, not as fact lists.
- Facts may be expressed in prose, structure, code, comments, tests, config, contracts, logs,
  listings, recipes, or mixed text.
- Facts may be distributed across multiple spans, but equivalence must still be justified by
  strongly anchored support in both directions.

Fact model:
- Preserve meaning-bearing qualifiers including negation, time, quantity, modality, exclusivity,
  causality, scope, identity, comparison, and conditions.
- Near-paraphrase is acceptable.
- Exact wording is not required.

Format-aware extraction examples:
- Craigslist listings, recipe steps, and declarative code constants must be interpreted as sources
  of structured factual claims before equivalence is judged.

Required strict examples:
- actual: "Agent's name is Roger."
  reference: "Agent's name is Roger."
  verdict: True
- actual: "Agent's name is Roger and he works in support."
  reference: "Agent's name is Roger."
  verdict: False
- actual: "Agent's name is Roger."
  reference: "Agent's name is Roger and he works in support."
  verdict: False
- actual: "Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: False
- actual: "Agent's name is Roger. Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: False
- actual: "we had so much fun yesterday"
  reference: "thanks for the dinner yesterday, that was amazing"
  closed-world verdict: False because dinner is not explicitly anchored
- actual: "Apple lost $1B because iPhone 17 Pro has bad camera and some other factors"
  reference: "Bad iPhone camera and bad speaker led to poor Apple returns"
  closed-world verdict: False because the speaker detail and precise financial claim do not align
  conservatively in both directions
- actual: "Bob likes apples. I like same fruits as Bob."
  reference: "I like apples."
  closed-world verdict: False because actual still asserts the extra fact "Bob likes apples"
- actual: "Agent introduced himself as Roger"
  reference: "Agent's name is Roger"
  closed-world verdict: False because the introduction event is not supported in reverse

Conflict rules:
- Conflict exists when two facts cannot both hold under a coherent interpretation of the same
  entities, events, times, scopes, and qualifiers.
- If conflict exists, the predicate must return False.

Empty-fact behavior:
- If both documents contain no extractable facts, return True.
- If exactly one document contains extractable facts, return False.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of actual.
3. Extract or derive the fact graph of reference.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Internally enumerate the actual facts, reference facts, support links, and conflict links.
6. Evaluate support from actual to reference using closed-world rules.
7. Evaluate support from reference to actual using closed-world rules.
8. Evaluate cross-document conflict conservatively.
9. Return True only if both support directions succeed and no conflict exists.
10. Otherwise return False.

Final reminder:
- This predicate requires two-way support and zero conflict. Extra actual content that reference
  does not support is enough to make the verdict False.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, state whether failure came from missing coverage, extra
  unsupported content, or conflict, or state that closed-world equivalence was satisfied.
"""

MATCHES_FACTS_TASK_TEMPLATE = """Evaluate the predicate matches_facts for the two documents below.

Actual document:
<actual>
{actual}
</actual>

Reference document:
<reference>
{reference}
</reference>
"""


matches_facts = LLMPredicate(
    predicate_name="matches_facts",
    normal_prompt=MATCHES_FACTS_NORMAL_PROMPT,
    strict_prompt=MATCHES_FACTS_STRICT_PROMPT,
    task_template=MATCHES_FACTS_TASK_TEMPLATE,
)

__all__ = ["matches_facts"]
