# RFC: Style, Layout, Topic, and Policy Predicates for LLM-as-a-Judge

**Status:** Draft
**Intended use:** Normative foundation for predicate APIs, evals, and downstream reasoning
**Version:** 0.1

## Abstract

This document specifies the semantics of four boolean predicates that evaluate non-factual properties of arbitrary strings:

* `matches_writing_style(actual: str, reference: str) -> bool`
* `matches_writing_layout(actual: str, reference: str) -> bool`
* `has_topic(actual: str, reference: str) -> bool`
* `follows_policy(actual: str, reference: str) -> bool`

These predicates are intentionally distinct from factual comparison predicates such as `has_facts` or `matches_facts`. They operate over different semantic dimensions:

* **style**: how something is expressed
* **layout**: how something is organized or formatted
* **topic**: what the text is about
* **policy**: whether the text satisfies a normative rule

This document defines the meaning of each predicate, the role of the `reference` argument, expected behavior on real-world inputs, and the boundaries between these concepts.

---

## 1. Conventions and Normative Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are normative.

Unless otherwise stated, all predicates return a boolean only. Implementations SHOULD internally track richer reasoning artifacts, but those artifacts are not part of the public contract defined here.

---

## 2. Goals

The goal of this predicate family is to provide precise, reusable semantic primitives for non-factual evaluation.

These predicates are intended to support:

* assertions in test suites
* judge prompts
* eval definitions
* report generation
* downstream metrics
* structured output validation
* content QA pipelines

The goal is not generic similarity scoring. Each predicate is intended to answer a narrow question with a stable meaning.

---

## 3. Non-Goals

This RFC does **not** define:

* factual correctness
* factual equivalence
* contradiction detection
* truthfulness
* semantic entailment in general

Those belong to the fact predicates defined elsewhere.

This RFC also does not define probabilistic similarity scores, ranking, or partial credit. The contract here is boolean.

---

## 4. Common Input Model

All four predicates operate on arbitrary strings. Inputs are **documents**, not necessarily sentences.

A valid input may be:

* prose
* email
* legal text
* chat transcript
* Reddit thread
* Markdown
* JSON
* YAML
* XML
* source code
* logs
* config files
* templates
* listings
* recipes

The implementation MUST NOT assume that the input is a clean natural-language paragraph.

The implementation SHOULD use format-aware interpretation where useful. For example:

* JSON may be interpreted structurally
* code may be interpreted via syntax, literals, comments, and identifiers
* Markdown may be interpreted as a document with headings, sections, and list items
* email may be interpreted as subject, greeting, body, and signoff
* threads may require aggregation across multiple comments

---

## 5. Dimensional Separation

This section is normative and extremely important.

The four predicates in this RFC evaluate four different dimensions:

### 5.1 Style

How the text is written.

Examples of style dimensions:

* formal vs informal
* plain vs ornate
* terse vs verbose
* direct vs hedged
* grammatical vs error-prone
* neutral vs dramatic
* technical vs colloquial

### 5.2 Layout

How the text is structured or formatted.

Examples of layout dimensions:

* JSON schema
* Markdown template
* email structure
* section ordering
* bullet format
* key/value arrangement
* heading pattern
* indentation and delimiters where structurally meaningful

### 5.3 Topic

What the text is about.

Examples:

* taxes
* database performance
* lease terms
* dog adoption
* GPU memory
* recipe ingredients

### 5.4 Policy

Whether the text satisfies a rule.

Examples:

* all names must be lowercase
* output must be valid JSON
* response must contain exactly 3 bullet points
* do not mention prices
* include a greeting and a signoff

These dimensions MUST NOT be collapsed into one another.

In particular:

* same topic does not imply same style
* same style does not imply same topic
* same layout does not imply same style
* follows_policy does not imply matches_writing_layout unless the policy explicitly constrains layout
* follows_policy does not imply matches_writing_style unless the policy explicitly constrains style
* `has_topic` says nothing about factual correctness

---

## 6. Role of the `reference` Argument

The role of `reference` differs by predicate.

### 6.1 `matches_writing_style(actual, reference)`

`reference` is a **reference document or sample** whose style is the target style.

### 6.2 `matches_writing_layout(actual, reference)`

`reference` is a **reference document, schema instance, or template example** whose layout is the target layout.

### 6.3 `has_topic(actual, reference)`

`reference` is a **topic specification string**, not a reference document.

Examples:

* `"database performance"`
* `"refund policy"`
* `"dogs"`
* `"Postgres indexing"`

### 6.4 `follows_policy(actual, reference)`

`reference` is a **policy specification string**, not a reference document.

Examples:

* `"all names must be lowercase"`
* `"must be valid JSON with keys name and email"`
* `"must not contain profanity"`

This distinction is normative. Implementations MUST interpret the second argument according to the predicate being called.

---

## 7. `matches_writing_style`

## 7.1 Definition

`matches_writing_style(actual, reference)` returns `True` iff `actual` and `reference` are written in materially the same writing style.

Style concerns **expression**, not subject matter.

This predicate answers:

* are these written in the same voice, register, wording profile, surface correctness profile, and rhetorical manner?

It does **not** answer:

* whether they say the same thing
* whether they have the same mood at the level of subject matter
* whether they are about the same topic
* whether they use the same layout

---

## 7.2 Style Signature

For semantic purposes, each document SHOULD be mapped to a **style signature**.

A style signature MAY include features such as:

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

---

## 7.3 What style must ignore

`matches_writing_style` MUST ignore differences in:

* facts
* topic
* stance
* truth
* event content
* semantic payload in general

Example:

* `"It's sad that he passed away"`
* `"We have a new agenda for this call"`

These MAY match in style if both are plain, direct, grammatical, non-ornate, and similarly worded.

By contrast:

* `"It's sad that he passed away"`
* `"Oh my dear Michael, for why did you leave us on this broken planet alone?"`

These SHOULD NOT match in style, because the second is highly dramatic, ornate, and rhetorically elevated, even though both concern grief or loss.

Important clarification: this predicate ignores **what emotion is being described**, but it does not ignore **how emotionally the writing is performed**.

---

## 7.4 Style is not layout

Two texts MAY match in style but not in layout.

Example:

* plain email
* plain bullet list

If both are written in the same plain, concise, grammatical corporate voice, `matches_writing_style` MAY be `True` even though layout differs.

Likewise, two texts MAY match in layout but not style.

Example:

* two emails with identical greeting/body/signoff pattern
* one written in clipped corporate language, the other in florid poetic language

Then layout may match while style does not.

---

## 7.5 Canonical examples

### Example A: same style, different topic

* actual: `"It's sad that he passed away."`
* reference: `"We have a new agenda for this call."`

Expected:

* `matches_writing_style = True`

Reason:

* both are short, plain, grammatically standard, direct, and non-ornate

### Example B: different style

* actual: `"It's sad that he passed away."`
* reference: `"Oh my dear Michael, for why did you leave us on this broken planet alone?"`

Expected:

* `matches_writing_style = False`

Reason:

* plain/direct vs dramatic/ornate/poetic

### Example C: same layout, different style

* actual: `"Hi team,\nWe need to reschedule.\nBest,\nNick"`
* reference: `"Dearest colleagues,\nMight we, with great humility, revisit the hour of our gathering?\nWarmest regards,\nNick"`

Expected:

* `matches_writing_style = False`

---

## 8. `matches_writing_layout`

## 8.1 Definition

`matches_writing_layout(actual, reference)` returns `True` iff `actual` and `reference` instantiate materially the same structural organization or formatting pattern.

Layout concerns **organization and format**, not wording, meaning, or factual correctness.

This predicate answers:

* are these arranged according to the same structural template?

It does **not** answer:

* whether they use the same style
* whether they say the same thing
* whether they concern the same topic

---

## 8.2 Layout Signature

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
* changelog entry with date/title/body
* Python function with docstring and return block
* SQL insert statement template

---

## 8.3 What layout must ignore

`matches_writing_layout` MUST ignore differences in:

* factual content
* topic
* wording
* tone
* grammar, except where grammar tokens are structurally part of the format
* values occupying content slots

Example:

```json
{"name":"roger","role":"agent"}
```

and

```json
{"name":"mike","role":"manager"}
```

These SHOULD match in layout if the relevant comparison is the same schema shape.

Example:

```md
# Summary
...
# Risks
...
# Next Steps
...
```

and another document with the same heading skeleton but different content SHOULD match in layout.

---

## 8.4 Layout may be exact or schema-like

Layout matching SHOULD be structural, not byte-for-byte.

For example:

* different JSON values should not break layout match
* different bullet text should not break layout match
* different email body text should not break layout match

However, a materially different template SHOULD break layout match.

Example:

* email format vs JSON
* Markdown checklist vs freeform paragraph
* JSON array vs JSON object
* different required section ordering, if order is part of the template

---

## 8.5 Canonical examples

### Example A: same JSON layout

* actual: `{"name":"roger","role":"agent"}`
* reference: `{"name":"mike","role":"manager"}`

Expected:

* `matches_writing_layout = True`

### Example B: different JSON layout

* actual: `{"name":"roger","role":"agent"}`
* reference: `{"user":{"name":"roger"},"roles":["agent"]}`

Expected:

* `matches_writing_layout = False`

### Example C: same email layout

* actual:
  `Hi team,\nWe are moving the meeting.\nBest,\nNick`
* reference:
  `Hello all,\nPlease review the attached draft.\nRegards,\nSara`

Expected:

* `matches_writing_layout = True`

---

## 9. `has_topic`

## 9.1 Definition

`has_topic(actual, reference)` returns `True` iff `actual` is substantively about the topic described by `reference`.

Here, `reference` is a **topic specification string**, not an example document.

This predicate answers:

* is the topic present as a meaningful subject of the document?

It does **not** answer:

* whether the document is factually correct about that topic
* whether the topic is approved, denied, praised, criticized, or prohibited
* whether the topic is the only topic present

---

## 9.2 Topic presence

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

Example:

* a document about `Postgres indexing` may have topic `database performance`
* a car listing for a Honda Civic has topic `cars`
* a recipe about pasta has topic `cooking`

---

## 9.3 Incidental mention does not count

A fleeting mention SHOULD NOT by itself count as topic presence.

Example:

* `"Please send the contract. Also, I drove a car to the office."`
* topic: `"cars"`

Expected:

* `has_topic = False`

Reason:

* cars are mentioned, but not substantively discussed

By contrast:

* `"Selling my 2018 Honda Civic, 82k miles, clean title."`
* topic: `"cars"`

Expected:

* `has_topic = True`

---

## 9.4 Topic is independent of stance

A topic MAY be present even if it is denied, criticized, or discussed hypothetically.

Example:

* `"This article argues against remote work."`
* topic: `"remote work"`

Expected:

* `has_topic = True`

This predicate concerns subject matter, not approval.

---

## 9.5 Topic is document-level, not keyword-level

Implementations SHOULD determine whether the topic is a real subject of the document, not whether a token appears.

This is especially important for:

* long threads
* code files
* config blobs
* legal text
* mixed-topic documents

---

## 9.6 Canonical examples

### Example A: topic present

* actual: `"We reduced query latency by adding indexes and tuning Postgres planner settings."`
* reference: `"database performance"`

Expected:

* `has_topic = True`

### Example B: incidental mention only

* actual: `"Please sign the lease. I parked the car outside."`
* reference: `"cars"`

Expected:

* `has_topic = False`

### Example C: topic in code

* actual:

  ```python
  def verify_jwt(token: str) -> Claims:
      ...
  ```
* reference: `"authentication"`

Expected:

* `has_topic = True`

if the implementation interprets JWT verification as substantively about authentication.

---

## 10. `follows_policy`

## 10.1 Definition

`follows_policy(actual, reference)` returns `True` iff `actual` satisfies the policy specified by `reference`.

Here, `reference` is a **policy specification string**.

A policy is a normative rule over the document.

Examples:

* `"all names must be lowercase"`
* `"must be valid JSON"`
* `"must include exactly one H1 heading"`
* `"must not mention pricing"`
* `"must contain greeting and signoff"`
* `"all bullets must start with '-'"`
* `"output must be under 100 words"`

---

## 10.2 Policy semantics

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

* `matches_writing_layout` asks: does actual resemble this reference structure?
* `follows_policy` asks: does actual obey this declared rule?

---

## 10.3 Compliance model

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

---

## 10.4 Policy ambiguity

If a policy is materially ambiguous or not assessable from `actual` alone, implementations SHOULD behave conservatively.

Recommended default:

* do not return `True` unless compliance is supported by the text and policy as given

This is especially important because a boolean compliance predicate is often used as a gate.

Examples of problematic policies:

* `"must be legally safe"` without jurisdiction or rule definition
* `"must use the best possible tone"`
* `"must be correct"` when correctness depends on external facts not available to the predicate

Such policies are underspecified for reliable boolean adjudication.

---

## 10.5 Policy may overlap with style or layout

Policies may constrain style or layout, but that does not collapse the concepts.

Example:

* policy: `"must be formal"`
* `follows_policy` checks compliance with that rule

That is not the same as:

* `matches_writing_style(actual, reference_formal_example)`

Likewise:

* policy: `"must be valid JSON with keys name and email"`
  is not the same as:
* `matches_writing_layout(actual, reference_json_example)`

A text may satisfy the policy without matching the example exactly, and vice versa.

---

## 10.6 Canonical examples

### Example A: lowercase names

* actual: `"alice met bob at the office"`
* reference: `"all names must be lowercase"`

Expected:

* `follows_policy = True`

### Example B: policy violation

* actual: `"Alice met bob at the office"`
* reference: `"all names must be lowercase"`

Expected:

* `follows_policy = False`

### Example C: layout policy

* actual: `{"name":"roger","email":"r@example.com"}`
* reference: `"must be valid JSON with keys name and email"`

Expected:

* `follows_policy = True`

### Example D: forbidden content

* actual: `"The plan costs $99/month"`
* reference: `"must not mention pricing"`

Expected:

* `follows_policy = False`

---

## 11. Relationships and Invariants

The following are intended semantic invariants.

### 11.1 Style independence

Two texts MAY match in style while differing completely in topic, semantics, and facts.

### 11.2 Layout independence

Two texts MAY match in layout while differing completely in style, topic, and facts.

### 11.3 Topic independence

Two texts MAY share topic while differing in style, layout, and factual truth.

### 11.4 Policy independence

A text MAY follow policy without matching a reference style or layout example.

### 11.5 Non-implications

The following implications MUST NOT be assumed:

* `matches_writing_style => matches_writing_layout`
* `matches_writing_layout => matches_writing_style`
* `has_topic => follows_policy`
* `follows_policy => has_topic`
* `has_topic => factual correctness`
* `matches_writing_style => same mood or same semantics`

That last point is especially important for your use case.

---

## 12. Real-World Input Behavior

Because inputs may be messy artifacts, implementations SHOULD be robust to mixed content.

### 12.1 Legal contract

* style may be legalistic
* layout may be sectioned clauses
* topic may be lease terms
* policy may require all defined terms to be capitalized

### 12.2 Reddit thread with 500 comments

* style may be inconsistent across comments
* topic may still be stable at thread level
* layout may be threaded conversation
* policy may require no profanity and fail if any included reply violates it, depending on scope

### 12.3 Source code

* topic may be authentication, retry logic, or schema parsing
* layout may be class/function template
* style may be terse/internal vs tutorial/comment-heavy
* policy may require snake_case or presence of type hints

### 12.4 JSON

* layout is usually strongly structural
* style is usually weak or irrelevant unless comments/string values carry prose
* topic may be recoverable from field names and values
* policy may constrain schema and value formatting

---

## 13. Recommended Implementation Posture

This section is non-normative but strongly recommended.

A robust implementation SHOULD compute each boolean from an explicit intermediate representation.

Recommended projections:

* `StyleSignature(actual)`
* `LayoutSignature(actual)`
* `TopicProfile(actual)`
* `PolicyConstraints(reference)` and `ComplianceCheck(actual, constraints)`

Then define:

* `matches_writing_style := EquivalentStyle(StyleSignature(actual), StyleSignature(reference))`
* `matches_writing_layout := EquivalentLayout(LayoutSignature(actual), LayoutSignature(reference))`
* `has_topic := TopicPresent(TopicProfile(actual), TopicSpec(reference))`
* `follows_policy := Satisfies(actual, PolicyConstraints(reference))`

This keeps the predicates stable and prevents cross-contamination between dimensions.

---

## 14. Short Reference Definitions

These are suitable for public docs.

* **matches_writing_style**
  Returns whether `actual` and `reference` are written in materially the same style, independent of topic and semantic content.

* **matches_writing_layout**
  Returns whether `actual` and `reference` use materially the same structural layout or template.

* **has_topic**
  Returns whether `actual` is substantively about the topic described by `reference`.

* **follows_policy**
  Returns whether `actual` satisfies the rule or constraints described by `reference`.

---

## 15. Summary

This RFC defines four non-factual predicates over arbitrary strings:

* style is about expression
* layout is about structure
* topic is about subject matter
* policy is about rule compliance

The crucial design rule is that these dimensions remain separate. A good implementation should be able to say:

* same style, different topic
* same layout, different style
* same topic, policy violation
* policy-compliant, but not layout-matching
* topic present, facts wrong

That separation is what keeps the API logically clean.

I can also turn both RFCs into a single unified spec with one shared ontology section and two predicate families: factual predicates and non-factual predicates.
