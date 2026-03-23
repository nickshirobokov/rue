"""LLM predicate for writing style matching."""

from .clients import LLMPredicate


MATCHES_WRITING_STYLE_NORMAL_PROMPT = """You are executing the boolean predicate matches_writing_style(actual, reference).

This prompt is a program specification, not a conversation. Evaluate whether the documents named
actual and reference are written in materially the same writing style. The output must follow the
response schema exactly. Reason internally. If the output schema requests an explanation, provide
a short style justification and nothing else.

The strict flag, if present, does not change the semantics of this predicate.

Semantic target:
- Return True if and only if actual and reference have materially the same writing style.
- Style concerns expression, not subject matter.
- This predicate asks whether the two documents have the same voice, register, wording profile,
  surface correctness profile, and rhetorical manner.
- This predicate does not ask whether the documents say the same thing.
- This predicate does not ask whether the documents have the same facts, topic, stance, or layout.

Reference role:
- Reference is a reference document or writing sample whose style is the target style.
- Do not interpret reference as a policy specification.
- Do not interpret reference as a topic specification.
- Do not interpret reference as a layout template.

Style model:
- Treat each document as having a style signature.
- A style signature may include register or formality, lexical sophistication, idiomaticity,
  directness versus hedging, sentence complexity, punctuation habits, rhetorical flourish,
  emotional expressiveness as writing manner, grammatical correctness, spelling correctness,
  terseness versus verbosity, conversational versus institutional voice, and technical versus
  colloquial wording.
- Style is a projection that abstracts away topic and propositional content.

What style must ignore:
- Facts.
- Topic.
- Stance.
- Truth.
- Event content.
- Semantic payload in general.
- Same emotion as subject matter does not matter.
- Important clarification: ignore what emotion is being described, but do not ignore how
  emotionally the writing itself is performed. Emotional restraint, melodrama, lament, exuberance,
  poetic mourning, and flat reportorial tone are style features.

Examples of required separation:
- "It's sad that he passed away." and "We have a new agenda for this call." may match in style if
  both are short, plain, direct, grammatical, and non-ornate.
- "It's sad that he passed away." and "Oh my dear Michael, for why did you leave us on this broken
  planet alone?" should not match in style because plain/direct is not the same as
  dramatic/ornate/poetic.
- Two texts may match in style but not in layout.
- Two texts may match in layout but not in style.

Input model:
- Treat actual and reference as arbitrary documents, not only natural-language paragraphs.
- Inputs may be prose, email, legal text, chat transcript, Markdown, code comments, logs, JSON
  with prose string values, templates, forum threads, or mixed text.
- Use format-aware interpretation when useful, but focus only on expression and writing manner.

Canonical examples:
- actual: "It's sad that he passed away."
  reference: "We have a new agenda for this call."
  verdict: True because both are short, plain, grammatical, direct, and non-ornate
- actual: "It's sad that he passed away."
  reference: "Oh my dear Michael, for why did you leave us on this broken planet alone?"
  verdict: False because the second is dramatic, ornate, and rhetorically elevated
- actual: "Hi team,\nWe need to reschedule.\nBest,\nNick"
  reference: "Dearest colleagues,\nMight we, with great humility, revisit the hour of our gathering?\nWarmest regards,\nNick"
  verdict: False because the layout is similar email structure but the styles differ materially

Decision criteria:
- Compare the documents at the level of style signature, not topic or fact overlap.
- Focus on materially shared writing manner, not exact wording.
- Minor wording differences do not matter if the style signature remains materially the same.
- Material changes in register, rhetorical elevation, verbosity profile, grammaticality, or voice
  should break the match.
- When evidence is mixed, judge whether a reasonable evaluator would treat the style as the same in
  substance rather than merely partially overlapping.

Decision procedure:
1. Interpret both inputs as documents.
2. Derive the style signature of actual.
3. Derive the style signature of reference.
4. Ignore topic, facts, stance, and layout except insofar as they leak into visible style.
5. Return True only if the style signatures are materially equivalent.
6. Otherwise return False.

Final reminder:
- Match on writing manner, not meaning. Two documents can differ completely in topic and still
  match in style, and two documents can share topic while clearly differing in style.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, briefly describe the key matching or mismatching style
  features.
"""

MATCHES_WRITING_STYLE_STRICT_PROMPT = MATCHES_WRITING_STYLE_NORMAL_PROMPT

MATCHES_WRITING_STYLE_TASK_TEMPLATE = """Evaluate the predicate matches_writing_style for the two documents below.

Actual document:
<actual>
{actual}
</actual>

Reference style sample:
<reference>
{reference}
</reference>
"""


matches_writing_style = LLMPredicate(
    predicate_name="matches_writing_style",
    normal_prompt=MATCHES_WRITING_STYLE_NORMAL_PROMPT,
    strict_prompt=MATCHES_WRITING_STYLE_STRICT_PROMPT,
    task_template=MATCHES_WRITING_STYLE_TASK_TEMPLATE,
)

__all__ = ["matches_writing_style"]
