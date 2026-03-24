"""LLM predicate for conflicting facts."""

from rue.predicates.clients import LLMPredicate


HAS_CONFLICTING_FACTS_NORMAL_PROMPT = """You are executing the boolean predicate has_conflicting_facts(actual, reference, strict=False).

This prompt is a program specification, not a conversation. Evaluate whether the documents named
actual and reference contain any pair of conflicting facts under open-world semantics. The output
must follow the response schema exactly. Reason internally. If the output schema requests an
explanation, provide a short factual justification and nothing else.

Semantic target:
- Return True if and only if at least one fact in actual conflicts with at least one fact in
  reference.
- Conflict is stronger than non-support.
- Mere extra content does not create conflict.
- Mere omission does not create conflict.
- A single contradictory pair is sufficient for True.

Document model:
- Treat both inputs as arbitrary documents, not as sentence lists.
- Documents may be prose, chat logs, listings, contracts, recipes, logs, JSON, YAML, XML, code,
  comments, tests, config, markdown, or mixed text.
- Facts may be explicit, structural, distributed across multiple spans, or connected through short
  reasoning chains.

Fact model:
- A fact is a proposition about the world, an entity, an event, a relation, a quantity, a time,
  a location, a cause, or an evaluative property that can be compared for support or contradiction.
- Preserve qualifiers. Negation, time, quantity, modality, exclusivity, causality, scope,
  identity, comparison, and conditions are part of the fact.
- Different wording can still describe the same underlying proposition or the same underlying
  conflict. Do not require exact lexical overlap.

Format-aware extraction examples:
- Craigslist listing facts such as model, mileage, owner count, title state, and maintenance
  status may conflict independently with claims in another document.
- Recipe facts such as ingredient count, temperature, and duration may conflict independently.
- Code or config like `MAX_RETRIES = 3` may conflict with "maximum retries is 5" when the text is
  acting as declarative configuration.

Conflict definition:
- Two facts conflict when they cannot both hold under a coherent interpretation of the same
  entities, events, times, scopes, and qualifiers.
- Determine conflict only after aligning entities, referents, event identity, time, and scope as
  justified by the text.
- Conflict examples include incompatible identities, incompatible quantities, incompatible time
  values, incompatible exclusive-cause claims, or incompatible mutually exclusive conditions.
- Examples: "Agent's name is Roger" conflicts with "Agent's name is Mike"; "The car has 80,000
  miles" conflicts with "The car has 120,000 miles"; "Apple gained $1B" conflicts with "Apple
  lost $1B"; "Camera was the only cause" conflicts with "Camera and speaker were causes."
- Conflict may arise through compositional reasoning, not only literal surface contradiction.
- Do not invent conflict from ungrounded facts. If pears are never grounded in the text, do not
  derive a support or conflict relation involving pears.

Non-conflict boundaries:
- "Agent's name is Roger" does not conflict with "Agent works in support."
- "The recipe uses eggs" does not conflict with "The recipe is quick to make."
- "We had fun yesterday" does not conflict with "We had dinner yesterday" merely because one does
  not support the other.
- Compatible supersets and subsets do not create conflict on their own.
- If facts can both be true together under a coherent grounded interpretation, do not mark
  conflict.

Open-world alignment rules:
- Open-world mode allows more flexible alignment of paraphrases, event descriptions, aliases, and
  underspecified references when the alignment is strongly plausible and grounded in the text.
- Open-world mode may resolve same-event or same-entity identity more permissively than
  closed-world mode.
- Even in open world, do not invent conflict from weak speculation.
- If ambiguity remains and incompatibility is not grounded, prefer no conflict.

Required examples:
- actual: "Agent's name is Roger and he works in support."
  reference: "Agent's name is Roger."
  verdict: False
- actual: "Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: True
- actual: "Agent's name is Roger. Agent's name is Mike."
  reference: "Agent's name is Roger."
  verdict: True because the Mike claim conflicts with the Roger claim in reference
- actual: "Roger is the agent and lives in SF"
  reference: "Roger is the agent"
  verdict: False because "lives in SF" is unsupported but not conflicting
- actual: "Apple lost $1B because iPhone 17 Pro has bad camera and some other factors"
  reference: "Bad iPhone camera and bad speaker led to poor Apple returns"
  verdict: False in open world because the texts can be reconciled rather than contradicted
- actual: "Bob likes apples. I like same fruits as Bob."
  reference: "I do not like apples."
  verdict: True because actual compositionally supports "I like apples," which conflicts with the
  reference claim

Empty-fact behavior:
- If either document contains no extractable facts, return False unless the other document also
  contains no facts, in which case return False as well.
- No pair of facts means no conflict.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of actual.
3. Extract or derive the fact graph of reference.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Internally enumerate candidate fact pairs and compare them after grounded alignment of
   entities, times, scopes, and qualifiers.
6. Return True as soon as one contradictory pair is found.
7. Return False if no contradictory pair exists.

Final reminder:
- Unsupported does not imply conflicting. Return True only for genuine incompatibility, not mere
  lack of support or extra compatible detail.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, identify the conflicting fact pair or state that no
  conflicting pair was found.
"""

HAS_CONFLICTING_FACTS_STRICT_PROMPT = """You are executing the boolean predicate has_conflicting_facts(actual, reference, strict=True).

This prompt is a program specification, not a conversation. Evaluate whether the documents named
actual and reference contain any pair of conflicting facts under closed-world semantics. The
output must follow the response schema exactly. Reason internally. If the output schema requests
an explanation, provide a short factual justification and nothing else.

Semantic target:
- Return True if and only if at least one fact in actual conflicts with at least one fact in
  reference.
- Conflict is stronger than non-support.
- A missing detail, a broad-vs-specific mismatch, or an extra compatible fact does not by itself
  create conflict.

Closed-world rules:
- Closed-world evaluation is conservative and text-bounded.
- Align entities, events, times, scopes, and qualifiers only when that alignment is strongly
  anchored in the text.
- Do not freely instantiate omitted details.
- Do not derive contradiction from vague text or weak commonsense completion.
- If ambiguity remains about whether two statements concern the same entity, event, or scope,
  prefer no conflict.

Document model:
- Treat both inputs as arbitrary documents.
- Facts may be expressed in prose, structure, code, comments, tests, config, contracts, listings,
  recipes, logs, or mixed text.
- Facts may be distributed across multiple spans, but conflict must remain grounded and explicit
  enough for conservative comparison.

Fact model:
- Keep meaning-bearing qualifiers intact: negation, time, quantity, modality, exclusivity,
  causality, scope, identity, comparison, and conditions.
- Different wording can still express conflicting propositions when the conflict is semantically
  clear and text-anchored.

Format-aware extraction examples:
- Craigslist attributes, recipe parameters, and declarative code constants may each participate in
  conflict once extracted as facts.

Required closed-world boundaries:
- "we had so much fun yesterday" versus "thanks for the dinner yesterday, that was amazing" is
  not a conflict. It is at most a support question.
- "Camera and some other factors caused the loss" versus "camera and speaker caused the loss" is
  not a conflict in closed world. The speaker detail is unsupported, not contradictory.
- "Apple had poor returns" versus "Apple lost $1B" is not automatically a conflict. It is a
  support granularity issue unless the text states incompatible facts.
- "Agent introduced himself as Roger" versus "Agent's name is Roger" is not a conflict.

Required direct conflict examples:
- "Agent's name is Roger" versus "Agent's name is Mike" is a conflict.
- "The agreement begins in January" versus "The agreement begins in March" is a conflict.
- "Camera was the only cause" versus "Camera and speaker were causes" is a conflict because the
  exclusivity claim is incompatible.
- "Bob likes apples. I like same fruits as Bob." versus "I do not like apples." is also a
  conflict because the first document compositionally supports "I like apples."

Empty-fact behavior:
- If either document contains no extractable facts, return False.
- If both contain no extractable facts, return False.

Decision procedure:
1. Interpret both inputs as documents.
2. Extract or derive the fact graph of actual.
3. Extract or derive the fact graph of reference.
4. Normalize entities, aliases, coreference, paraphrases, quantities, and dates across both fact
   graphs before comparison.
5. Internally enumerate fact pairs and compare them only when same-entity or same-event alignment
   is strongly grounded.
6. Return True as soon as one contradictory pair is found.
7. Return False if no such pair exists.

Final reminder:
- Do not mistake unsupported detail for contradiction. Return True only when the two documents
  cannot coherently both be true on the same grounded interpretation.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, identify the conflicting pair or state that no conflict
  was found.
"""

HAS_CONFLICTING_FACTS_TASK_TEMPLATE = """Evaluate the predicate has_conflicting_facts for the two documents below.

Actual document:
<actual>
{actual}
</actual>

Reference document:
<reference>
{reference}
</reference>
"""


has_conflicting_facts = LLMPredicate(
    predicate_name="has_conflicting_facts",
    normal_prompt=HAS_CONFLICTING_FACTS_NORMAL_PROMPT,
    strict_prompt=HAS_CONFLICTING_FACTS_STRICT_PROMPT,
    task_template=HAS_CONFLICTING_FACTS_TASK_TEMPLATE,
)

__all__ = ["has_conflicting_facts"]
