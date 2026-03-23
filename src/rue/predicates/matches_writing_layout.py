"""LLM predicate for writing layout matching."""

from .clients import LLMPredicate


MATCHES_WRITING_LAYOUT_NORMAL_PROMPT = """You are executing the boolean predicate matches_writing_layout(actual, reference).

This prompt is a program specification, not a conversation. Evaluate whether the documents named
actual and reference instantiate materially the same structural organization or formatting pattern.
The output must follow the response schema exactly. Reason internally. If the output schema
requests an explanation, provide a short layout justification and nothing else.

The strict flag, if present, does not change the semantics of this predicate.

Semantic target:
- Return True if and only if actual and reference use materially the same layout or template.
- Layout concerns organization and format, not wording, meaning, truth, tone, or topic.
- This predicate asks whether the documents are arranged according to the same structural pattern.
- This predicate does not ask whether they say the same thing.
- This predicate does not ask whether they have the same style.
- This predicate does not ask whether they concern the same topic.

Reference role:
- Reference is a reference document, schema instance, or template example whose layout is the
  target layout.
- Do not treat reference as a policy specification.
- Do not treat reference as a topic specification.

Layout model:
- Treat each document as having a layout signature.
- A layout signature may include document type or serialization family, section structure, section
  ordering, field or key structure, heading hierarchy, list structure, table shape, placeholder
  slots, wrapper patterns, delimiters where structurally meaningful, schema shape, and template
  skeleton.
- Evaluate structure, not content slot values.

What layout must ignore:
- Factual content.
- Topic.
- Wording.
- Tone.
- Grammar, except where grammar tokens are structurally part of the format.
- Values occupying content slots.
- Different JSON values should not break a layout match.
- Different bullet text should not break a layout match.
- Different email body text should not break a layout match.

Structural posture:
- Layout matching should be structural, not byte-for-byte.
- Schema-like matching is valid.
- Materially different templates should not match.
- Examples of layout differences that should break the match:
  email format versus JSON
  Markdown checklist versus freeform paragraph
  JSON array versus JSON object
  changed required section ordering when order is part of the template

Canonical examples:
- actual: {"name":"roger","role":"agent"}
  reference: {"name":"mike","role":"manager"}
  verdict: True because the schema shape is the same
- actual: {"name":"roger","role":"agent"}
  reference: {"user":{"name":"roger"},"roles":["agent"]}
  verdict: False because the structural shape is materially different
- actual: "Hi team,\nWe are moving the meeting.\nBest,\nNick"
  reference: "Hello all,\nPlease review the attached draft.\nRegards,\nSara"
  verdict: True because both instantiate the same greeting-body-signoff email layout

Input model:
- Treat actual and reference as arbitrary documents.
- Inputs may be prose, email, legal text, chat transcript, Markdown, JSON, YAML, XML, source
  code, logs, config, templates, listings, recipes, or mixed-format text.
- Use format-aware interpretation where useful.

Decision criteria:
- Compare structural organization, not semantic payload.
- Compare serialization family and schema shape where relevant.
- Compare heading patterns, section ordering, list structure, wrappers, delimiters, and field
  arrangement where relevant.
- Ignore content-slot values unless they themselves alter the structure.
- Return False when the structural template is materially different even if the topic or style is
  similar.

Decision procedure:
1. Interpret both inputs as documents.
2. Derive the layout signature of actual.
3. Derive the layout signature of reference.
4. Ignore wording, facts, topic, and tone except where needed to identify structure.
5. Return True only if the layout signatures are materially equivalent.
6. Otherwise return False.

Final reminder:
- Match on structural template, not on wording or values. Same content can appear in different
  layouts, and different content can occupy the same layout.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, briefly identify the key structural match or mismatch.
"""

MATCHES_WRITING_LAYOUT_STRICT_PROMPT = MATCHES_WRITING_LAYOUT_NORMAL_PROMPT

MATCHES_WRITING_LAYOUT_TASK_TEMPLATE = """Evaluate the predicate matches_writing_layout for the two documents below.

Actual document:
<actual>
{actual}
</actual>

Reference layout sample:
<reference>
{reference}
</reference>
"""


matches_writing_layout = LLMPredicate(
    predicate_name="matches_writing_layout",
    normal_prompt=MATCHES_WRITING_LAYOUT_NORMAL_PROMPT,
    strict_prompt=MATCHES_WRITING_LAYOUT_STRICT_PROMPT,
    task_template=MATCHES_WRITING_LAYOUT_TASK_TEMPLATE,
)

__all__ = ["matches_writing_layout"]
