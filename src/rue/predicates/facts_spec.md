# RFC: Fact-Matching Predicates for LLM-as-a-Judge

**Status:** Draft
**Intended use:** Normative foundation for predicate APIs, evals, and downstream reasoning
**Version:** 0.1

## Abstract

This document specifies the semantics of four boolean predicates for factual comparison between two input strings:

* `has_facts(actual: str, reference: str, strict: bool) -> bool`
* `has_unsupported_facts(actual: str, reference: str, strict: bool) -> bool`
* `has_conflicting_facts(actual: str, reference: str, strict: bool) -> bool`
* `matches_facts(actual: str, reference: str, strict: bool) -> bool`

The predicates operate over **facts** asserted, entailed, or supported by arbitrary strings. Inputs are not assumed to be clean lists of atomic facts; they may be natural language prose, conversations, legal contracts, Craigslist listings, recipe text, JSON, programming code, forum threads, or other text artifacts.

This specification defines:

* what counts as a fact
* how support and conflict are determined
* how open-world and closed-world evaluation differ
* how paraphrase, reformulation, and transfer through connections are handled
* how the four predicates relate logically

This document is normative for predicate behavior. Implementation details are intentionally left open where they do not affect semantics.

---

## 1. Conventions and Normative Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are to be interpreted as normative requirements.

In this document:

* `strict=True` means **closed-world** evaluation
* `strict=False` means **open-world** evaluation

This mapping is normative.

---

## 2. Goals

The goal of this predicate family is to provide a stable semantic layer for factual evaluation. These predicates are intended to be foundational primitives for:

* assertions in tests
* eval definitions
* judge prompts
* error analysis
* dataset labeling
* metric derivation
* report generation

The design goal is not “general semantic similarity.” The goal is explicit factual comparison with logically constrained outcomes.

---

## 3. Non-Goals

This predicate family does **not** define evaluation for:

* policy compliance
* style or tone
* instruction following
* behavioral quality
* conversational strategy
* whether a model asked a follow-up question
* whether a response was formal, polite, concise, etc.

These may be evaluated elsewhere, but they are out of scope here unless they are re-expressed as factual propositions and intentionally treated as such.

Example:

* `"Agent's name is Roger"` is in scope as a fact.
* `"Agent introduced themself by name Roger"` is primarily a behavioral/policy statement and is out of scope unless the system intentionally treats discourse acts as facts.

Important nuance: a statement may support a factual conclusion even if its wording is behavioral. For example, `"Agent introduced himself as Roger"` can support `"Agent's name is Roger"`. This is allowed because the first statement contains evidence for the second. The target of evaluation remains factual.

---

## 4. Inputs

Each predicate takes:

* `actual: str`
* `reference: str`
* `strict: bool`

Semantically, `actual` and `reference` are treated as **documents**, not mere sentences.

A document may contain:

* one fact
* many facts
* zero facts
* noisy facts
* contradictory facts
* non-factual content mixed with factual content
* facts distributed across multiple lines, records, comments, clauses, functions, or examples

The implementation MUST NOT assume that inputs are clean fact lists.

Examples of valid input forms include:

* prose paragraphs
* Craigslist listings
* legal contracts
* Reddit threads with many comments
* recipes
* logs
* JSON
* YAML
* XML
* program source code
* comments in code
* markdown documents
* transcripts

The system SHOULD perform format-aware interpretation when useful. For example:

* JSON keys and values may be interpreted structurally
* code literals, assignments, signatures, or comments may express facts
* contract clauses may require clause-level extraction rather than sentence splitting

---

## 5. Core Model

## 5.1 Fact

A **fact** is a proposition about the world, an entity, an event, a relation, a quantity, a time, a location, a causal connection, or an asserted evaluative property, such that the proposition can be compared for support or contradiction.

Examples:

* `The car has 80,000 miles`
* `The lease term is 24 months`
* `Bob likes apples`
* `The function returns a boolean`
* `The recipe uses two eggs`
* `Roger is the agent`
* `The loss was caused by camera problems`
* `Pulp Fiction is a good movie`

A fact includes its relevant qualifiers. These qualifiers MUST NOT be discarded when they change meaning. Relevant qualifiers include:

* negation
* time
* quantity
* modality / certainty
* exclusivity
* causality
* scope
* identity / coreference
* comparison
* conditions

Examples:

* `Apple lost money`
* `Apple lost $1B`
* `Apple may have lost $1B`
* `Apple lost $1B only because of camera issues`

These are not interchangeable.

---

## 5.2 Evidence-bearing document

A document is an arbitrary string from which the system derives a set or graph of factual propositions.

Facts may be:

* explicitly stated
* distributed across multiple spans
* recoverable through coreference
* recoverable through structural interpretation
* recoverable through limited reasoning anchored in the text

A document need not resemble ordinary prose.

---

## 5.3 Fact graph

For semantic purposes, each document SHOULD be modeled as a **fact graph**, not merely an unordered bag of statements.

A fact graph may contain:

* fact nodes
* entity nodes
* event nodes
* relation edges
* coreference edges
* alias / paraphrase links
* entailment links
* causal links
* compositional links

This matters because support may arise not only from direct wording overlap, but from connected facts.

Example:

* `Bob likes apples.`
* `I like same fruits as Bob.`

These two statements jointly support:

* `I like apples.`

That support is not recoverable from naive sentence matching. It requires graph composition:

* Bob likes apples
* I like same fruits as Bob
* therefore I like apples

Likewise:

* `Agent introduced himself as Roger`

supports:

* `Agent's name is Roger`

because introducing oneself as X is evidence of name identity.

---

## 6. Support

## 6.1 Definition

A fact `f` is **supported by** a document `D` if the factual content of `D`, interpreted under the current world assumption, is sufficient to justify treating `f` as true for the purpose of comparison.

Support is directional.

Support is **not** string equality and is **not** shallow semantic similarity.

Support MAY arise from:

* direct assertion
* paraphrase
* equivalent reformulation
* coreference resolution
* structural extraction
* bounded entailment through explicit connections
* compositional transfer across linked facts

---

## 6.2 Types of support

An implementation SHOULD recognize at least the following support classes.

### 6.2.1 Direct support

The fact is stated explicitly.

Example:

* document: `The car has 80,000 miles.`
* supported fact: `The car has 80,000 miles.`

### 6.2.2 Paraphrastic support

Different wording, same proposition.

Example:

* document: `The vehicle has 80k miles on it.`
* supported fact: `The car has 80,000 miles.`

### 6.2.3 Structural support

The fact is represented in a non-prose format.

Example JSON:

```json
{
  "agent_name": "Roger",
  "status": "active"
}
```

supports:

* `Agent's name is Roger`
* `Agent is active`

Example code:

```python
AGENT_NAME = "Roger"
```

may support:

* `Agent's name is Roger`

if the relevant interpretation context treats the assignment as declarative data rather than arbitrary unrelated code text.

### 6.2.4 Compositional support

Multiple facts combine to support a new fact.

Example:

* `Bob likes apples.`
* `I like same fruits as Bob.`

supports:

* `I like apples.`

### 6.2.5 Discourse-act-derived support

A statement about what someone said or presented supports a factual conclusion about the content conveyed.

Example:

* `Agent introduced himself as Roger`

supports:

* `Agent's name is Roger`

This support is permitted because the discourse act conveys identity content.

### 6.2.6 Summarization / abstraction support

A more detailed fact may support a broader fact, and in open-world mode a broader fact may sometimes support a more specific one.

Example:

* `Apple lost $1B`
  supports:
* `Apple had poor returns`

Open-world mode MAY also permit the reverse in limited contexts, but that is more permissive and must remain text-anchored.

---

## 6.3 Boundedness of support

Support through reasoning MUST remain bounded and text-anchored.

The system MUST NOT invent ungrounded facts.

Allowed:

* derive `I like apples` from explicitly linked premises

Not allowed:

* derive `I like pears` unless pears are grounded somewhere in the text

Open-world evaluation expands what counts as acceptable support, but does not permit arbitrary guessing.

---

## 7. Conflict

## 7.1 Definition

Two facts conflict if they cannot both hold under a coherent interpretation of the same entities, events, times, scopes, and qualifiers.

Conflict is stronger than non-support.

Examples of conflict:

* `Agent's name is Roger` vs `Agent's name is Mike`
* `The car has 80,000 miles` vs `The car has 120,000 miles`
* `Apple gained $1B` vs `Apple lost $1B`
* `Camera was the only cause` vs `Camera and speaker were causes`
* `The agreement begins in January` vs `The agreement begins in March`

Examples of non-support without conflict:

* `Agent's name is Roger` vs `Agent works in support`
* `The recipe uses eggs` vs `The recipe is quick to make`
* `We had fun yesterday` vs `We had dinner yesterday`

Conflict MAY also arise through compositional reasoning, not only literal surface contradiction.

---

## 8. World Assumptions

## 8.1 Closed world (`strict=True`)

Closed-world evaluation treats the document as text-bounded and comparatively literal.

Under closed world:

* only explicit content and near-paraphrase count by default
* bounded inference is allowed only when the connection is strongly anchored in the text
* unfilled placeholders are not freely instantiated
* omitted qualifiers are not assumed
* vague descriptions are not freely mapped to precise values
* broad commonsense completion is minimized

Closed world does **not** mean “no reasoning at all.” It means reasoning is conservative.

Examples:

* `Bob likes apples. I like same fruits as Bob.`
  Closed world SHOULD still support `I like apples`, because the transfer is explicitly licensed by the text.
* `Agent introduced himself as Roger`
  Closed world SHOULD support `Agent's name is Roger`, because identity is explicitly conveyed.
* `We had so much fun yesterday`
  Closed world SHOULD NOT support `We had dinner yesterday`.
* `Apple had poor returns`
  Closed world SHOULD NOT support `Apple lost $1B`.
* `Camera and some other factors caused the loss`
  Closed world SHOULD NOT support `speaker issues caused the loss`.

So the key distinction is not “reasoning vs no reasoning.” The distinction is:

* closed world allows **anchored semantic consequence**
* open world also allows **reasonable completion under underspecification**

---

## 8.2 Open world (`strict=False`)

Open-world evaluation permits broader support through reasonable implication and completion, provided the inference remains grounded in the document.

Under open world:

* broad and specific descriptions may align more permissively
* underspecified remainder phrases may be instantiated if the compared fact fits naturally
* event co-reference may be resolved with more flexibility
* abstract descriptions may support concrete restatements when strongly plausible in context
* missing detail may be filled in if text strongly points there and no contradiction arises

Examples:

* `We had so much fun yesterday` may support `Thanks for the dinner yesterday, that was amazing` if context suggests the same event.
* `Camera and some other factors caused the loss` may support `camera and speaker caused the loss` if the compared speaker claim is a reasonable instantiation of the remainder phrase in context.
* `Apple had poor returns` may support `Apple lost $1B` only if the implementation intentionally permits that specificity jump and the context makes it reasonable.

Open world is permissive, not reckless.

---

## 9. Predicate Definitions

Let:

* `A` be the fact graph derived from `actual`
* `R` be the fact graph derived from `reference`

Let:

* `Supports(X, f, strict)` mean fact graph `X` supports fact `f`
* `Conflicts(X, f, strict)` mean fact graph `X` contains at least one fact that conflicts with `f`
* equivalently, pairwise conflict can be defined between facts in `A` and `R`

---

## 9.1 `has_facts(actual, reference, strict)`

### Definition

Returns `True` iff every fact asserted by `reference` is supported by `actual`.

### Formal condition

For every reference fact `r` in `R`, `A` supports `r`.

### Reading

This is a **coverage** predicate from `reference` to `actual`.

It answers:

* does actual contain or support all reference facts?

It does **not** answer:

* whether actual contains extra facts
* whether actual contains contradictions elsewhere
* whether actual factually equals reference

### Consequences

Extra content in `actual` does not affect this predicate unless it destroys support or changes the interpretation so that the supported fact no longer holds.

---

## 9.2 `has_unsupported_facts(actual, reference, strict)`

### Definition

Returns `True` iff `actual` contains at least one fact not supported by `reference`.

### Formal condition

There exists some fact `a` in `A` such that `R` does not support `a`.

### Reading

This is an **extra-content / unbacked-content** predicate from `actual` to `reference`.

It answers:

* does actual assert anything factual that reference does not support?

This includes benign additions, over-claims, and contradictory additions.

### Consequences

A fact can be unsupported without being conflicting.

Example:

* actual: `Roger is the agent and lives in SF`
* reference: `Roger is the agent`

Here, `lives in SF` is unsupported but not conflicting.

---

## 9.3 `has_conflicting_facts(actual, reference, strict)`

### Definition

Returns `True` iff at least one fact in `actual` conflicts with at least one fact in `reference`.

### Formal condition

There exists some `a` in `A` and some `r` in `R` such that `a` conflicts with `r`.

### Reading

This is a contradiction predicate.

It answers:

* do the two documents contain mutually incompatible factual content?

It does not require full overlap. A single contradiction is sufficient.

---

## 9.4 `matches_facts(actual, reference, strict)`

### Definition

Returns `True` iff the two documents are factually equivalent under the selected world assumption.

### Formal condition

Equivalent to all of the following:

* every reference fact is supported by actual
* every actual fact is supported by reference
* no facts conflict between the two

One operational definition is:

`matches_facts = has_facts AND NOT has_unsupported_facts AND NOT has_conflicting_facts`

### Reading

This is the strongest predicate. It is factual equivalence, not just similarity.

---

## 10. Invariants

The following invariants SHOULD hold.

### 10.1 Equivalence implies coverage and consistency

If `matches_facts(...)` is `True`, then:

* `has_facts(...)` MUST be `True`
* `has_unsupported_facts(...)` MUST be `False`
* `has_conflicting_facts(...)` MUST be `False`

### 10.2 Conflict rules out match

If `has_conflicting_facts(...)` is `True`, then:

* `matches_facts(...)` MUST be `False`

### 10.3 Support and contradiction are independent

It is valid for `has_facts(...)` and `has_conflicting_facts(...)` to both be `True`.

Example:

* actual: `Agent's name is Roger. Agent's name is Mike.`
* reference: `Agent's name is Roger.`

Coverage exists, but contradiction also exists.

### 10.4 Unsupported does not imply conflict

It is valid for `has_unsupported_facts(...)` to be `True` while `has_conflicting_facts(...)` is `False`.

---

## 11. Document Interpretation Rules

## 11.1 General rule

The implementation MUST interpret facts from arbitrary strings, not only sentence-like lists.

The system SHOULD use document-aware extraction strategies, including:

* sentence and clause parsing for prose
* record/key parsing for structured formats
* AST or syntax-aware parsing for code when helpful
* section-level reasoning for contracts
* comment aggregation for forum threads or discussions

### Examples

#### Craigslist listing

`2018 Honda Civic, 82k miles, one owner, clean title, needs brake pads soon`

Possible facts include:

* the car is a 2018 Honda Civic
* mileage is 82,000
* ownership count is one
* title is clean
* brake pads need replacement soon

#### Recipe

`Add 2 eggs, whisk with sugar, bake at 350F for 25 minutes`

Possible facts include:

* the recipe uses 2 eggs
* the baking temperature is 350F
* baking duration is 25 minutes

#### Reddit thread

Facts may appear across multiple comments and may require aggregation or disambiguation. The implementation SHOULD compare asserted document-level content, not merely the top comment or first sentence.

#### Programming code

Code MAY express facts through:

* constants
* config values
* schema fields
* return types
* comments
* examples
* tests

Example:

```python
MAX_RETRIES = 3
```

may support:

* maximum retries is 3

if the comparison context treats this as declarative configuration rather than arbitrary unrelated source text.

---

## 12. Fact Identity, Paraphrase, and Transfer Through Connections

This section is central.

## 12.1 Surface wording is not identity

Different wording may express the same fact.

Examples:

* `Bob enjoys apples` supports `Bob likes apples`
* `The vehicle has 80k miles` supports `The car has 80,000 miles`
* `Roger introduced himself` may support `Roger identified himself`

A compliant implementation MUST NOT require lexical overlap as the primary basis for support.

---

## 12.2 Support may transfer through explicit connections

Facts may support other facts through relations explicitly provided in the document.

Example:

* `Bob likes apples.`
* `I like same fruits as Bob.`

supports:

* `I like apples.`

This is normative. A compliant implementation SHOULD allow support through connected propositions when the chain is short, explicit, and text-anchored.

Additional example:

* `Alice owns the same car model as Bob.`
* `Bob drives a 2021 Corolla.`

may support:

* `Alice owns a 2021 Corolla`

if the implementation interprets “same car model” at that level of specificity.

---

## 12.3 Discourse acts may support world facts

Example:

* `Agent introduced himself as Roger`

supports:

* `Agent's name is Roger`

This is normative.

Reason: the first statement contains identity evidence about the agent. The support is not based on superficial wording; it is based on the semantics of self-introduction.

---

## 12.4 Bound on transfer

Support transfer SHOULD be bounded.

Recommended default:

* short chains only
* explicit textual anchors required
* ambiguous transfer SHOULD fail in closed world
* ambiguous transfer MAY succeed in open world if strongly plausible and contradiction-free

---

## 13. Closed-World and Open-World Examples

## 13.1 Fun vs dinner

### actual

`we had so much fun yesterday`

### reference

`thanks for the dinner yesterday, that was amazing`

#### Closed world

Expected:

* `has_facts = False`
* `has_unsupported_facts = True`
* `has_conflicting_facts = False`
* `matches_facts = False`

Reason:

* same-day positive event is present
* dinner is not explicit
* no contradiction exists

#### Open world

Expected:

* `has_facts = True`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = True`

Reason:

* the positive event may reasonably be interpreted as the dinner event

---

## 13.2 Camera, speaker, and losses

### actual

`Apple lost $1B because iPhone 17 Pro has bad camera and some other factors`

### reference

`Bad iPhone camera and bad speaker led to poor Apple returns`

#### Closed world

Expected:

* `has_facts = False`
* `has_unsupported_facts = True`
* `has_conflicting_facts = False`
* `matches_facts = False`

Reason:

* camera overlaps
* speaker is not explicit
* poor returns is not identical to $1B loss
* “some other factors” is not sufficient to name speaker in closed world

#### Open world

Expected:

* `has_facts = True`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = True`

Reason:

* speaker may be a reasonable instantiation of “some other factors”
* $1B loss may support poor returns

---

## 13.3 Transfer through connection

### actual

`Bob likes apples. I like same fruits as Bob.`

### reference

`I like apples.`

#### Closed world

Expected:

* `has_facts = True`

Reason:

* the transfer is explicitly licensed by the text and does not require open-world completion

#### Open world

Expected:

* also `has_facts = True`

---

## 13.4 Identity through introduction

### actual

`Agent introduced himself as Roger`

### reference

`Agent's name is Roger`

#### Closed world

Expected:

* `has_facts = True`

Reason:

* this is anchored semantic consequence, not speculative inference

---

## 14. Canonical Truth Table Examples

## 14.1 Exact equivalence

### actual

`Agent's name is Roger.`

### reference

`Agent's name is Roger.`

Expected:

* `has_facts = True`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = True`

---

## 14.2 Compatible superset

### actual

`Agent's name is Roger and he works in support.`

### reference

`Agent's name is Roger.`

Expected:

* `has_facts = True`
* `has_unsupported_facts = True`
* `has_conflicting_facts = False`
* `matches_facts = False`

---

## 14.3 Compatible subset

### actual

`Agent's name is Roger.`

### reference

`Agent's name is Roger and he works in support.`

Expected:

* `has_facts = False`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = False`

---

## 14.4 Direct contradiction

### actual

`Agent's name is Mike.`

### reference

`Agent's name is Roger.`

Expected:

* `has_facts = False`
* `has_unsupported_facts = True`
* `has_conflicting_facts = True`
* `matches_facts = False`

---

## 14.5 Coverage plus contradiction

### actual

`Agent's name is Roger. Agent's name is Mike.`

### reference

`Agent's name is Roger.`

Expected:

* `has_facts = True`
* `has_unsupported_facts = True`
* `has_conflicting_facts = True`
* `matches_facts = False`

---

## 15. Empty-Fact Behavior

Let a document contain no extractable facts.

### 15.1 Empty reference

If `reference` contains no facts, then:

* `has_facts` MUST be `True`

Reason: vacuous coverage.

### 15.2 Empty actual

If `actual` contains no facts, then:

* `has_unsupported_facts` MUST be `False`

Reason: there are no actual facts to be unsupported.

### 15.3 Both empty

If both contain no facts:

* `has_facts = True`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = True`

### 15.4 One empty, one non-empty

If actual is empty and reference is not:

* `has_facts = False`
* `matches_facts = False`

If reference is empty and actual is not:

* `has_facts = True`
* `has_unsupported_facts = True`
* `matches_facts = False`

---

## 16. Recommended Evaluation Procedure

This section is non-normative but strongly recommended.

A robust implementation SHOULD compute booleans from intermediate structured state, not from a direct one-shot verdict.

Recommended pipeline:

1. Interpret `actual` and `reference` as documents
2. Extract or derive fact graphs from both
3. Normalize:

   * entities
   * aliases
   * coreference
   * paraphrases
   * quantities and dates where possible
4. Compute support links under the selected world assumption
5. Compute conflict links
6. Derive:

   * covered reference facts
   * unsupported actual facts
   * conflicting fact pairs
7. Aggregate into the four booleans

Internal artifacts SHOULD ideally include:

* extracted facts
* support justifications
* conflict justifications
* inferred transfer links
* mode used
* ambiguity markers

Even if the public API returns only `bool`, this internal structure is critical for debugging, eval traceability, and future extensibility.

---

## 17. Recommended Public Descriptions

These are suitable for docs or inline API reference.

* **has_facts**
  Returns whether every fact in `reference` is supported by `actual`.

* **has_unsupported_facts**
  Returns whether `actual` contains at least one fact not supported by `reference`.

* **has_conflicting_facts**
  Returns whether any fact in `actual` conflicts with any fact in `reference`.

* **matches_facts**
  Returns whether `actual` and `reference` are factually equivalent under the selected world assumption.

---

## 18. Design Notes

## 18.1 Coverage is not equivalence

This is the single most important semantic distinction in the API.

`has_facts` is a coverage predicate.
It is not an equality predicate.

A system that collapses these concepts will produce confusing eval behavior.

## 18.2 Closed world is conservative, not brain-dead

Closed world still allows:

* paraphrase
* identity reformulation
* direct semantic transfer through explicit links

It merely blocks speculative completion.

## 18.3 Inputs are documents, not sentences

This family must remain stable on messy real-world artifacts. If the implementation only works on clean English statements, it is too weak for production use.

---

## 19. Future Extensions

This RFC intentionally limits the public output to booleans. Future compatible extensions may expose:

* supporting spans
* unsupported spans
* conflict spans
* extracted fact objects
* confidence / ambiguity metadata
* explanation traces
* typed fact classes
* configurable transfer depth
* explicit contradiction categories

These extensions SHOULD preserve the semantics in this RFC.

---

## 20. Summary

This specification defines a fact-comparison API over arbitrary document strings. It treats factual support as a semantic relation, not a wording match. It permits support through paraphrase, structure, and bounded transfer across explicit factual connections. It distinguishes conservative closed-world evaluation from more permissive open-world evaluation. And it keeps the four predicates logically separate:

* coverage
* unsupported content
* contradiction
* equivalence

That separation is the backbone of the design.

If you want, I can do the next pass as a polished “v1.0 internal RFC” with cleaner naming, tighter examples, and an appendix called “Edge Cases and Adjudication Rules” for dates, quantities, negation, causality, and lists.
