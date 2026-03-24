# RFC: Semantic Predicates

**Status:** Draft
**Intended use:** Normative foundation for predicate APIs, evals, assertions, and downstream reasoning
**Version:** 1.0

## Abstract

This document specifies a unified semantic predicate suite for evaluating arbitrary strings as documents.

It defines two predicate families:

**Factual predicates**

* `has_facts(actual: str, reference: str, strict: bool) -> bool`
* `has_unsupported_facts(actual: str, reference: str, strict: bool) -> bool`
* `has_conflicting_facts(actual: str, reference: str, strict: bool) -> bool`
* `matches_facts(actual: str, reference: str, strict: bool) -> bool`

**Non-factual predicates**

* `matches_writing_style(actual: str, reference: str) -> bool`
* `matches_writing_layout(actual: str, reference: str) -> bool`
* `has_topic(actual: str, reference: str) -> bool`
* `follows_policy(actual: str, reference: str) -> bool`

These predicates are intentionally separate. They evaluate different dimensions of documents:

* **facts**: what propositions are supported or contradicted
* **style**: how something is expressed
* **layout**: how something is organized or formatted
* **topic**: what something is about
* **policy**: whether something satisfies a normative rule

This RFC defines shared input assumptions, the semantics of each predicate, the role of the `reference` argument, the meaning of `strict`, logical invariants, and recommended implementation posture.

---

## 1. Conventions and Normative Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

Unless otherwise stated, all predicates return only `bool`.

Implementations SHOULD internally compute richer intermediate artifacts, but those artifacts are not part of the public contract defined here.

For factual predicates only:

* `strict=True` means **closed-world** evaluation
* `strict=False` means **open-world** evaluation

This mapping is normative.

---

## 2. Goals

The goal of this predicate suite is to provide stable semantic primitives for document evaluation that can be reused across:

* test assertions
* eval definitions
* judge prompts
* structured output validation
* report generation
* dataset labeling
* error analysis
* downstream metrics
* content QA pipelines

The design goal is not generic similarity scoring. Each predicate answers a narrow question with a stable meaning.

---

## 3. Non-Goals

This RFC does not define:

* generic semantic similarity scores
* ranking
* partial credit
* probabilistic similarity metrics
* conversational quality as a whole
* whether a model behaved optimally in a broad sense

In particular:

* factual predicates do not define style, tone, or policy compliance
* non-factual predicates do not define factual correctness, factual equivalence, or contradiction detection unless those are explicitly re-expressed as policy constraints

---

## 4. Common Input Model

All predicates operate on arbitrary strings interpreted as **documents**, not necessarily sentences.

A valid input may be:

* prose
* email
* chat transcript
* legal text
* Reddit thread
* Markdown
* JSON
* YAML
* XML
* source code
* logs
* config files
* templates
* recipes
* listings

The implementation MUST NOT assume that the input is a clean natural-language paragraph or a list of atomic statements.

The implementation SHOULD use format-aware interpretation where useful. For example:

* JSON may be interpreted structurally
* code may be interpreted via syntax, literals, comments, and identifiers
* Markdown may be interpreted via headings, sections, and lists
* email may be interpreted as subject, greeting, body, and signoff
* threads may require aggregation across comments

---

## 5. Shared Semantic Separation

This section is normative and central.

The predicate suite evaluates different dimensions that MUST NOT be collapsed into one another.

### 5.1 Facts

What propositions are asserted, supported, or contradicted.

### 5.2 Style

How the text is written.

Examples:

* formal vs informal
* plain vs ornate
* terse vs verbose
* direct vs hedged
* grammatical vs error-prone
* technical vs colloquial

### 5.3 Layout

How the text is structured or formatted.

Examples:

* JSON schema shape
* Markdown template
* email structure
* section ordering
* heading hierarchy
* list structure

### 5.4 Topic

What the text is about.

Examples:

* lease terms
* database performance
* taxes
* dog adoption
* authentication

### 5.5 Policy

Whether the text satisfies a rule.

Examples:

* all names must be lowercase
* must be valid JSON
* must contain exactly 3 bullet points
* must not mention pricing
* include greeting and signoff

### 5.6 Required non-implications

The following MUST NOT be assumed:

* same facts implies same style
* same style implies same facts
* same layout implies same style
* same topic implies factual correctness
* follows policy implies same layout unless the policy explicitly constrains layout
* follows policy implies same style unless the policy explicitly constrains style
* `has_topic` says nothing about truth
* `matches_facts` says nothing about style or layout
* `matches_writing_style` says nothing about facts

---

## 6. Predicate Catalog

### 6.1 Factual family

These predicates compare factual content between `actual` and `reference` under a world assumption controlled by `strict`.

* `has_facts`: coverage from `reference` to `actual`
* `has_unsupported_facts`: extra factual content in `actual` not supported by `reference`
* `has_conflicting_facts`: contradiction between `actual` and `reference`
* `matches_facts`: factual equivalence

### 6.2 Non-factual family

These predicates evaluate non-factual semantic dimensions.

* `matches_writing_style`: expression equivalence
* `matches_writing_layout`: structural/template equivalence
* `has_topic`: topic presence
* `follows_policy`: rule compliance

---

# Part I. Factual Predicates

## 7. Inputs

Each factual predicate takes:

* `actual: str`
* `reference: str`
* `strict: bool`

Semantically, both inputs are documents that may contain:

* one fact
* many facts
* zero facts
* contradictory facts
* noisy or mixed factual and non-factual content
* facts distributed across multiple lines, clauses, comments, functions, records, or sections

The implementation MUST NOT assume clean fact lists.

---

## 8. Core Factual Model

### 8.1 Fact

A **fact** is a proposition about the world, an entity, an event, a relation, a quantity, a time, a location, a causal connection, or an asserted evaluative property, such that the proposition can be compared for support or contradiction.

Examples:

* The car has 80,000 miles.
* The lease term is 24 months.
* Bob likes apples.
* The function returns a boolean.
* The recipe uses two eggs.
* Roger is the agent.
* The loss was caused by camera problems.
* Pulp Fiction is a good movie.

A fact includes relevant qualifiers. These qualifiers MUST NOT be discarded when they change meaning.

Relevant qualifiers include:

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

For example, the following are not interchangeable:

* Apple lost money.
* Apple lost $1B.
* Apple may have lost $1B.
* Apple lost $1B only because of camera issues.

### 8.2 Evidence-bearing document

A document is an arbitrary string from which the system derives factual propositions.

Facts may be:

* explicitly stated
* distributed across multiple spans
* recoverable through coreference
* recoverable through structural interpretation
* recoverable through bounded reasoning anchored in the text

### 8.3 Fact graph

For semantic purposes, each document SHOULD be modeled as a **fact graph**, not just a bag of strings.

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

This matters because support may arise through explicit connections.

Example:

* `Bob likes apples.`
* `I like same fruits as Bob.`

These jointly support:

* `I like apples.`

Likewise:

* `Agent introduced himself as Roger`

supports:

* `Agent's name is Roger.`

---

## 9. Support

### 9.1 Definition

A fact `f` is **supported by** a document `D` if the factual content of `D`, interpreted under the current world assumption, is sufficient to justify treating `f` as true for comparison.

Support is directional.

Support is not string equality and is not shallow semantic similarity.

### 9.2 Types of support

A compliant implementation SHOULD recognize at least these classes.

#### 9.2.1 Direct support

The fact is explicitly stated.

#### 9.2.2 Paraphrastic support

Different wording, same proposition.

Example:

* `The vehicle has 80k miles on it.`
  supports
* `The car has 80,000 miles.`

#### 9.2.3 Structural support

The fact appears in non-prose form.

Example JSON:

```json
{"agent_name":"Roger","status":"active"}
```

supports:

* Agent's name is Roger.
* Agent is active.

Example code:

```python
AGENT_NAME = "Roger"
```

may support:

* Agent's name is Roger.

#### 9.2.4 Compositional support

Multiple facts combine to support another fact.

Example:

* `Bob likes apples.`
* `I like same fruits as Bob.`

supports:

* `I like apples.`

#### 9.2.5 Discourse-act-derived support

A discourse act conveys factual content.

Example:

* `Agent introduced himself as Roger`

supports:

* `Agent's name is Roger.`

#### 9.2.6 Summarization / abstraction support

A detailed fact may support a broader fact, and open-world mode MAY allow broader-to-more-specific support in limited grounded cases.

### 9.3 Boundedness of support

Support through reasoning MUST remain bounded and text-anchored.

The system MUST NOT invent ungrounded facts.

Allowed:

* deriving `I like apples` from explicitly connected premises

Not allowed:

* deriving `I like pears` unless pears are grounded in the text

---

## 10. Conflict

### 10.1 Definition

Two facts conflict if they cannot both hold under a coherent interpretation of the same entities, events, times, scopes, and qualifiers.

Conflict is stronger than non-support.

Examples of conflict:

* Agent's name is Roger. vs Agent's name is Mike.
* The car has 80,000 miles. vs The car has 120,000 miles.
* Apple gained $1B. vs Apple lost $1B.
* Camera was the only cause. vs Camera and speaker were causes.
* The agreement begins in January. vs The agreement begins in March.

Examples of non-support without conflict:

* Agent's name is Roger. vs Agent works in support.
* The recipe uses eggs. vs The recipe is quick to make.

Conflict MAY arise through compositional reasoning, not only literal contradiction.

---

## 11. World Assumptions

## 11.1 Closed world (`strict=True`)

Closed-world evaluation treats the document as text-bounded and conservative.

Under closed world:

* only explicit content and near-paraphrase count by default
* bounded inference is allowed only when strongly anchored in the text
* unfilled placeholders are not freely instantiated
* omitted qualifiers are not assumed
* vague descriptions are not freely mapped to precise values
* broad commonsense completion is minimized

Closed world still allows anchored semantic consequence.

Examples that SHOULD succeed in closed world:

* `Bob likes apples. I like same fruits as Bob.` supports `I like apples.`
* `Agent introduced himself as Roger` supports `Agent's name is Roger.`

Examples that SHOULD fail in closed world:

* `We had so much fun yesterday` does not support `We had dinner yesterday.`
* `Apple had poor returns` does not support `Apple lost $1B.`
* `Camera and some other factors caused the loss` does not support `speaker issues caused the loss.`

## 11.2 Open world (`strict=False`)

Open-world evaluation permits broader support through reasonable grounded completion.

Under open world:

* broad and specific descriptions may align more permissively
* underspecified remainder phrases may be instantiated if the compared fact fits naturally
* event co-reference may be resolved with more flexibility
* abstract descriptions may support concrete restatements when strongly plausible in context
* missing detail may be filled if the text strongly points there and no contradiction arises

Open world is permissive, not reckless.

It still MUST remain text-anchored.

---

## 12. Predicate Definitions

Let:

* `A` be the fact graph derived from `actual`
* `R` be the fact graph derived from `reference`

Let:

* `Supports(X, f, strict)` mean fact graph `X` supports fact `f`
* `Conflicts(X, f, strict)` mean fact graph `X` contains at least one fact that conflicts with `f`

### 12.1 `has_facts(actual, reference, strict)`

Returns `True` iff every fact asserted by `reference` is supported by `actual`.

Formal condition:

* for every reference fact `r` in `R`, `A` supports `r`

Reading:

* coverage from `reference` to `actual`

It does not ask:

* whether `actual` contains extra facts
* whether `actual` conflicts elsewhere
* whether `actual` is equivalent to `reference`

### 12.2 `has_unsupported_facts(actual, reference, strict)`

Returns `True` iff `actual` contains at least one fact not supported by `reference`.

Formal condition:

* there exists some fact `a` in `A` such that `R` does not support `a`

Reading:

* extra or unbacked factual content in `actual`

A fact can be unsupported without being conflicting.

Example:

* actual: `Roger is the agent and lives in SF.`
* reference: `Roger is the agent.`

Here, `lives in SF` is unsupported but not conflicting.

### 12.3 `has_conflicting_facts(actual, reference, strict)`

Returns `True` iff at least one fact in `actual` conflicts with at least one fact in `reference`.

Formal condition:

* there exists some `a` in `A` and some `r` in `R` such that `a` conflicts with `r`

Reading:

* contradiction exists between the documents

A single contradiction is sufficient.

### 12.4 `matches_facts(actual, reference, strict)`

Returns `True` iff the documents are factually equivalent under the selected world assumption.

Equivalent to all of:

* every reference fact is supported by `actual`
* every actual fact is supported by `reference`
* no facts conflict between them

Operationally:

* `matches_facts = has_facts AND NOT has_unsupported_facts AND NOT has_conflicting_facts`

---

## 13. Factual Invariants

The following SHOULD hold.

### 13.1 Equivalence implies coverage and consistency

If `matches_facts(...)` is `True`, then:

* `has_facts(...)` MUST be `True`
* `has_unsupported_facts(...)` MUST be `False`
* `has_conflicting_facts(...)` MUST be `False`

### 13.2 Conflict rules out match

If `has_conflicting_facts(...)` is `True`, then:

* `matches_facts(...)` MUST be `False`

### 13.3 Support and contradiction are independent

It is valid for `has_facts(...)` and `has_conflicting_facts(...)` to both be `True`.

Example:

* actual: `Agent's name is Roger. Agent's name is Mike.`
* reference: `Agent's name is Roger.`

### 13.4 Unsupported does not imply conflict

It is valid for `has_unsupported_facts(...)` to be `True` while `has_conflicting_facts(...)` is `False`.

---

## 14. Empty-Fact Behavior

Let a document contain no extractable facts.

### 14.1 Empty reference

If `reference` contains no facts, then:

* `has_facts` MUST be `True`

### 14.2 Empty actual

If `actual` contains no facts, then:

* `has_unsupported_facts` MUST be `False`

### 14.3 Both empty

If both contain no facts:

* `has_facts = True`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = True`

### 14.4 One empty, one non-empty

If actual is empty and reference is not:

* `has_facts = False`
* `matches_facts = False`

If reference is empty and actual is not:

* `has_facts = True`
* `has_unsupported_facts = True`
* `matches_facts = False`

---

## 15. Canonical Factual Examples

### 15.1 Exact equivalence

actual:
`Agent's name is Roger.`

reference:
`Agent's name is Roger.`

Expected:

* `has_facts = True`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = True`

### 15.2 Compatible superset

actual:
`Agent's name is Roger and he works in support.`

reference:
`Agent's name is Roger.`

Expected:

* `has_facts = True`
* `has_unsupported_facts = True`
* `has_conflicting_facts = False`
* `matches_facts = False`

### 15.3 Compatible subset

actual:
`Agent's name is Roger.`

reference:
`Agent's name is Roger and he works in support.`

Expected:

* `has_facts = False`
* `has_unsupported_facts = False`
* `has_conflicting_facts = False`
* `matches_facts = False`

### 15.4 Direct contradiction

actual:
`Agent's name is Mike.`

reference:
`Agent's name is Roger.`

Expected:

* `has_facts = False`
* `has_unsupported_facts = True`
* `has_conflicting_facts = True`
* `matches_facts = False`

### 15.5 Coverage plus contradiction

actual:
`Agent's name is Roger. Agent's name is Mike.`

reference:
`Agent's name is Roger.`

Expected:

* `has_facts = True`
* `has_unsupported_facts = True`
* `has_conflicting_facts = True`
* `matches_facts = False`

### 15.6 Transfer through connection

actual:
`Bob likes apples. I like same fruits as Bob.`

reference:
`I like apples.`

Expected:

* `has_facts = True` in both modes

### 15.7 Identity through introduction

actual:
`Agent introduced himself as Roger.`

reference:
`Agent's name is Roger.`

Expected:

* `has_facts = True` in closed world

---

# Part II. Non-Factual Predicates

## 16. Inputs

Each non-factual predicate takes:

* `actual: str`
* `reference: str`

These predicates do not use `strict`.

They operate over arbitrary documents and SHOULD be format-aware where helpful.

---

## 17. Role of the `reference` Argument

The role of `reference` differs by predicate.

### 17.1 `matches_writing_style(actual, reference)`

`reference` is a **reference document or sample** whose style is the target style.

### 17.2 `matches_writing_layout(actual, reference)`

`reference` is a **reference document, schema instance, or template example** whose layout is the target layout.

### 17.3 `has_topic(actual, reference)`

`reference` is a **topic specification string**, not a reference document.

Examples:

* `database performance`
* `refund policy`
* `dogs`
* `Postgres indexing`

### 17.4 `follows_policy(actual, reference)`

`reference` is a **policy specification string**, not a reference document.

Examples:

* `all names must be lowercase`
* `must be valid JSON with keys name and email`
* `must not contain profanity`

This distinction is normative.

---

## 18. `matches_writing_style`

### 18.1 Definition

`matches_writing_style(actual, reference)` returns `True` iff `actual` and `reference` are written in materially the same writing style.

Style concerns **expression**, not subject matter.

It asks:

* are these written in the same voice, register, wording profile, correctness profile, and rhetorical manner?

It does not ask:

* whether they say the same thing
* whether they have the same topic
* whether they use the same layout
* whether they are factually equivalent

### 18.2 Style signature

For semantic purposes, each document SHOULD be mapped to a **style signature**.

A style signature MAY include:

* register / formality
* lexical sophistication
* idiomaticity
* directness vs hedging
* sentence complexity
* punctuation habits
* rhetorical flourish
* emotional expressiveness as a writing manner
* grammatical correctness
* spelling correctness
* terseness / verbosity
* conversational vs institutional voice
* technical vs non-technical wording

A compliant implementation MUST treat style as a projection that abstracts away topic and propositional content.

### 18.3 What style must ignore

`matches_writing_style` MUST ignore differences in:

* facts
* topic
* stance
* truth
* event content
* semantic payload in general

Example:

* `It's sad that he passed away.`
* `We have a new agenda for this call.`

These MAY match in style if both are plain, direct, grammatical, and non-ornate.

By contrast:

* `It's sad that he passed away.`
* `Oh my dear Michael, for why did you leave us on this broken planet alone?`

These SHOULD NOT match in style.

Important clarification:
this predicate ignores **what emotion is being described**, but not **how emotionally the writing is performed**.

### 18.4 Style is not layout

Two texts MAY match in style but not layout.

Two texts MAY match in layout but not style.

---

## 19. `matches_writing_layout`

### 19.1 Definition

`matches_writing_layout(actual, reference)` returns `True` iff `actual` and `reference` instantiate materially the same structural organization or formatting pattern.

Layout concerns **organization and format**, not wording, meaning, topic, or truth.

It asks:

* are these arranged according to the same structural template?

### 19.2 Layout signature

For semantic purposes, each document SHOULD be mapped to a **layout signature**.

A layout signature MAY include:

* document type or serialization family
* section structure
* section ordering
* field/key structure
* heading hierarchy
* list structure
* table shape
* placeholder slots
* wrapper patterns
* delimiters where structurally meaningful
* schema shape
* template skeleton

Examples of layout families:

* JSON object with keys `name`, `email`, `role`
* Markdown doc with sections `Summary`, `Risks`, `Next Steps`
* email with greeting, body, signoff
* changelog entry with date, title, body

### 19.3 What layout must ignore

`matches_writing_layout` MUST ignore differences in:

* factual content
* topic
* wording
* tone
* grammar, except where grammar tokens are structurally meaningful
* values occupying content slots

Example:

```json
{"name":"roger","role":"agent"}
```

and

```json
{"name":"mike","role":"manager"}
```

SHOULD match in layout if the relevant comparison is schema shape.

### 19.4 Layout may be exact or schema-like

Layout matching SHOULD be structural, not byte-for-byte.

Different values SHOULD NOT break a layout match.

A materially different template SHOULD break a layout match.

Examples that SHOULD differ:

* email vs JSON
* Markdown checklist vs freeform paragraph
* JSON array vs JSON object
* different required section ordering, when order is part of the template

---

## 20. `has_topic`

### 20.1 Definition

`has_topic(actual, reference)` returns `True` iff `actual` is substantively about the topic described by `reference`.

Here, `reference` is a topic specification string.

It asks:

* is the topic present as a meaningful subject of the document?

It does not ask:

* whether the document is correct about that topic
* whether the topic is approved or condemned
* whether the topic is the only topic present

### 20.2 Topic presence

A topic is present when it is a substantive subject of the document.

Topic presence MAY be established through:

* direct mention
* paraphrase
* alias
* synonym
* hypernym / hyponym relation
* sustained discussion
* structural placement indicating subject matter
* code/config semantics where the content clearly concerns the topic

Topic presence MUST be semantic, not merely lexical.

Examples:

* a document about Postgres indexing may have topic `database performance`
* a Honda Civic listing may have topic `cars`
* a JWT verification function may have topic `authentication`

### 20.3 Incidental mention does not count

A fleeting mention SHOULD NOT by itself count as topic presence.

Example:

* actual: `Please send the contract. Also, I drove a car to the office.`
* topic: `cars`

Expected:

* `has_topic = False`

By contrast:

* actual: `Selling my 2018 Honda Civic, 82k miles, clean title.`
* topic: `cars`

Expected:

* `has_topic = True`

### 20.4 Topic is independent of stance

A topic MAY be present even if it is denied, criticized, or discussed hypothetically.

Example:

* `This article argues against remote work.`
* topic: `remote work`

Expected:

* `has_topic = True`

---

## 21. `follows_policy`

### 21.1 Definition

`follows_policy(actual, reference)` returns `True` iff `actual` satisfies the policy specified by `reference`.

Here, `reference` is a policy specification string.

A policy is a normative rule over the document.

Examples:

* `all names must be lowercase`
* `must be valid JSON`
* `must include exactly one H1 heading`
* `must not mention pricing`
* `must contain greeting and signoff`
* `all bullets must start with '-'`
* `output must be under 100 words`

### 21.2 Policy semantics

A policy MAY impose requirements on:

* content
* forbidden content
* lexical forms
* casing
* structure
* formatting
* style
* length
* ordering
* presence / absence of sections
* schema validity
* token-level patterns

A policy is not a similarity target. It is a rule.

This is the core distinction from `matches_writing_style` and `matches_writing_layout`.

### 21.3 Compliance model

For semantic purposes, a policy SHOULD be interpreted as a set of constraints.

Constraint types MAY include:

* universal constraints
  example: `all names must be lowercase`
* existential constraints
  example: `must include a signoff`
* negative constraints
  example: `must not mention prices`
* cardinality constraints
  example: `must contain exactly 3 bullet points`
* structural constraints
  example: `must be valid JSON with keys name and email`
* style constraints
  example: `must be formal and concise`

`follows_policy` returns `True` iff all applicable constraints are satisfied.

If any constraint is violated, the result MUST be `False`.

### 21.4 Policy ambiguity

If a policy is materially ambiguous or not assessable from `actual` alone, implementations SHOULD behave conservatively.

Recommended default:

* do not return `True` unless compliance is supported by the text and the policy as given

Examples of underspecified policies:

* `must be legally safe`
* `must use the best possible tone`
* `must be correct` when correctness depends on external facts

### 21.5 Policy may overlap with style or layout

Policies may constrain style or layout, but that does not collapse the concepts.

Example:

* policy: `must be formal`

This is not the same as:

* `matches_writing_style(actual, formal_reference_example)`

Likewise:

* policy: `must be valid JSON with keys name and email`

is not the same as:

* `matches_writing_layout(actual, reference_json_example)`

---

## 22. Canonical Non-Factual Examples

### 22.1 Same style, different topic

actual:
`It's sad that he passed away.`

reference:
`We have a new agenda for this call.`

Expected:

* `matches_writing_style = True`

### 22.2 Different style

actual:
`It's sad that he passed away.`

reference:
`Oh my dear Michael, for why did you leave us on this broken planet alone?`

Expected:

* `matches_writing_style = False`

### 22.3 Same JSON layout

actual:
`{"name":"roger","role":"agent"}`

reference:
`{"name":"mike","role":"manager"}`

Expected:

* `matches_writing_layout = True`

### 22.4 Different JSON layout

actual:
`{"name":"roger","role":"agent"}`

reference:
`{"user":{"name":"roger"},"roles":["agent"]}`

Expected:

* `matches_writing_layout = False`

### 22.5 Topic present

actual:
`We reduced query latency by adding indexes and tuning Postgres planner settings.`

reference:
`database performance`

Expected:

* `has_topic = True`

### 22.6 Incidental mention only

actual:
`Please sign the lease. I parked the car outside.`

reference:
`cars`

Expected:

* `has_topic = False`

### 22.7 Lowercase names policy

actual:
`alice met bob at the office`

reference:
`all names must be lowercase`

Expected:

* `follows_policy = True`

### 22.8 Policy violation

actual:
`Alice met bob at the office`

reference:
`all names must be lowercase`

Expected:

* `follows_policy = False`

### 22.9 Layout policy

actual:
`{"name":"roger","email":"r@example.com"}`

reference:
`must be valid JSON with keys name and email`

Expected:

* `follows_policy = True`

### 22.10 Forbidden content

actual:
`The plan costs $99/month`

reference:
`must not mention pricing`

Expected:

* `follows_policy = False`

---

# Part III. Cross-Family Relationships

## 23. Cross-Family Invariants and Non-Implications

The suite is designed so that the same pair of documents can differ independently along factual and non-factual dimensions.

Valid outcomes include:

* same style, different facts
* same layout, different style
* same topic, conflicting facts
* policy-compliant, but not layout-matching
* topic present, but facts wrong
* factual match, but different style
* factual match, but different layout

The following implications MUST NOT be assumed:

* `matches_facts => matches_writing_style`
* `matches_facts => matches_writing_layout`
* `matches_writing_style => matches_facts`
* `matches_writing_layout => matches_facts`
* `has_topic => has_facts`
* `follows_policy => matches_writing_layout`
* `follows_policy => matches_writing_style`

---

# Part IV. Real-World Input Behavior

## 24. Examples by Artifact Type

### 24.1 Legal contract

* facts may include term length, parties, payment obligations
* style may be legalistic
* layout may be sectioned clauses
* topic may be lease terms
* policy may require all defined terms to be capitalized

### 24.2 Reddit thread with many comments

* facts may be distributed across comments
* style may vary across comments
* topic may still be stable at thread level
* layout may be threaded conversation
* policy may require no profanity and may fail depending on scope

### 24.3 Source code

* facts may arise from constants, schemas, comments, examples, return types
* style may be terse, internal, tutorial-like, or comment-heavy
* layout may be class/function/template structure
* topic may be authentication, retry logic, schema parsing
* policy may require snake_case or type hints

### 24.4 JSON

* facts may arise from keys and values
* layout is often strongly structural
* style is often weak or irrelevant unless prose appears in values
* topic may be recoverable from schema and content
* policy may constrain schema or formatting

---

# Part V. Recommended Implementation Posture

## 25. Internal Projections

This section is non-normative but strongly recommended.

A robust implementation SHOULD compute each boolean from explicit intermediate representations.

Suggested projections:

* `FactGraph(actual)`
* `FactGraph(reference)`
* `StyleSignature(document)`
* `LayoutSignature(document)`
* `TopicProfile(document)`
* `PolicyConstraints(reference)`

Then define:

* `has_facts := Covered(FactGraph(actual), FactGraph(reference), strict)`
* `has_unsupported_facts := ExtraFacts(FactGraph(actual), FactGraph(reference), strict)`
* `has_conflicting_facts := AnyConflict(FactGraph(actual), FactGraph(reference), strict)`
* `matches_facts := FactualEquivalence(...)`
* `matches_writing_style := EquivalentStyle(StyleSignature(actual), StyleSignature(reference))`
* `matches_writing_layout := EquivalentLayout(LayoutSignature(actual), LayoutSignature(reference))`
* `has_topic := TopicPresent(TopicProfile(actual), TopicSpec(reference))`
* `follows_policy := Satisfies(actual, PolicyConstraints(reference))`

This helps keep the dimensions stable and prevents cross-contamination.

## 26. Recommended Evaluation Procedure

A robust implementation SHOULD:

1. Interpret `actual` and `reference` as documents.
2. Parse format-aware structure where useful.
3. Extract or derive internal representations for the relevant dimension.
4. Normalize entities, aliases, coreference, quantities, and dates where relevant.
5. Compute support and conflict for factual predicates.
6. Compute signatures or constraint checks for non-factual predicates.
7. Aggregate to booleans.

Internal artifacts SHOULD ideally include:

* extracted facts
* support justifications
* conflict justifications
* style and layout signatures
* topic evidence
* policy constraint checks
* ambiguity markers
* world assumption used for factual predicates

Even if the public API returns only `bool`, these artifacts are critical for debugging and eval traceability.

---

# Part VI. Public Reference Definitions

## 27. Short Definitions

* **has_facts**
  Returns whether every fact in `reference` is supported by `actual`.

* **has_unsupported_facts**
  Returns whether `actual` contains at least one fact not supported by `reference`.

* **has_conflicting_facts**
  Returns whether any fact in `actual` conflicts with any fact in `reference`.

* **matches_facts**
  Returns whether `actual` and `reference` are factually equivalent under the selected world assumption.

* **matches_writing_style**
  Returns whether `actual` and `reference` are written in materially the same style, independent of topic and semantic content.

* **matches_writing_layout**
  Returns whether `actual` and `reference` use materially the same structural layout or template.

* **has_topic**
  Returns whether `actual` is substantively about the topic described by `reference`.

* **follows_policy**
  Returns whether `actual` satisfies the rule or constraints described by `reference`.

---

# Part VII. Summary

## 28. Summary

This RFC defines a unified semantic predicate suite for arbitrary document strings.

It keeps eight predicates logically distinct across two families:

**Factual**

* coverage
* unsupported content
* contradiction
* equivalence

**Non-factual**

* style
* layout
* topic
* policy

The key design rule is separation of dimensions. A good implementation must be able to say, independently:

* same facts, different style
* same style, different topic
* same layout, different facts
* topic present, facts wrong
* policy-compliant, but not layout-matching
* factual match, but policy violation

That separation is what keeps the API predictable, composable, and useful in production.

If you want, I can do a second pass that makes this look more like a polished internal RFC with cleaner section numbering, an appendix for edge cases like dates and quantities, and a shorter API-reference version for docs.
