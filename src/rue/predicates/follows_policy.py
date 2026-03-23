"""LLM predicate for policy compliance."""

from .clients import LLMPredicate


FOLLOWS_POLICY_NORMAL_PROMPT = """You are executing the boolean predicate follows_policy(actual, reference).

This prompt is a program specification, not a conversation. Evaluate whether the document named
actual satisfies the policy specification named reference. The output must follow the response
schema exactly. Reason internally. If the output schema requests an explanation, provide a short
compliance justification and nothing else.

The strict flag, if present, does not change the semantics of this predicate.

Semantic target:
- Return True if and only if actual satisfies the rule or set of constraints described by
  reference.
- Reference is a policy specification string, not a sample document and not a style or layout
  target.
- Policy evaluation is rule compliance, not semantic similarity.
- If any applicable policy constraint is violated, return False.
- Return True only when compliance is supported by the text and the policy as given.

Dimensional separation:
- Do not treat policy as factual correctness unless the policy explicitly defines a check that can
  be evaluated from actual alone.
- Do not collapse policy into style matching.
- Do not collapse policy into layout matching.
- Do not collapse policy into topic presence.
- A document may follow policy without matching any reference style or layout example.
- A document may match a style or layout example and still violate policy.

Input model:
- Treat actual as an arbitrary document, not necessarily prose.
- Actual may be prose, email, legal text, chat transcript, Reddit thread, Markdown, JSON, YAML,
  XML, source code, logs, config, templates, listings, recipes, or mixed-format text.
- Interpret format-aware structure when useful. JSON may need structural validation. Markdown may
  need heading or list analysis. Code may need identifier, syntax, and comment interpretation.

Policy model:
- Interpret reference as a set of constraints.
- Constraint types may include universal constraints, existential constraints, negative
  constraints, cardinality constraints, structural constraints, style constraints, formatting
  constraints, casing constraints, ordering constraints, schema constraints, length constraints,
  and token-pattern constraints.
- Examples:
  all names must be lowercase
  must include a signoff
  must not mention prices
  must contain exactly 3 bullet points
  must be valid JSON with keys name and email
  must be formal and concise
- All applicable constraints must be satisfied for True.

What to evaluate:
- Content requirements and forbidden content.
- Lexical forms, casing, and token patterns when required by the policy.
- Structure and formatting when required by the policy.
- Length or cardinality when required by the policy.
- Presence or absence of required sections, fields, headings, bullets, keys, or signoffs when
  specified.
- Schema validity when the policy makes schema part of the rule.

Scope discipline:
- Apply each constraint only at the scope stated by the policy text.
- If a policy says "exactly these top-level keys", evaluate exactness only at the top level unless
  the policy also constrains nested objects or arrays.
- If a policy says each object in an array must contain certain keys, treat that as a minimum
  requirement for those objects unless the policy also says nested objects may contain no other
  keys.
- A prohibition on numbered lists applies to list formatting, not to ordinary prose that happens
  to contain numbers, times, quantities, or phrases such as "step 2".

What not to assume:
- Do not assume any constraint not stated or clearly implied by the policy text.
- Do not use external facts or outside world knowledge to certify compliance unless the policy is
  assessable from actual alone.
- Do not return True on vague, underspecified, or non-assessable policies unless compliance is
  clearly demonstrable from the text.

Ambiguity handling:
- If the policy is materially ambiguous, underdefined, or not reliably assessable from actual
  alone, behave conservatively.
- Recommended default: return False unless compliance is clearly supported.
- Examples of underspecified policies:
  must be legally safe
  must use the best possible tone
  must be correct
- These should not be treated as satisfied merely because there is no obvious violation.

Canonical examples:
- actual: "alice met bob at the office"
  reference: "all names must be lowercase"
  verdict: True
- actual: "Alice met bob at the office"
  reference: "all names must be lowercase"
  verdict: False
- actual: {"name":"roger","email":"r@example.com"}
  reference: "must be valid JSON with keys name and email"
  verdict: True
- actual: "The plan costs $99/month"
  reference: "must not mention pricing"
  verdict: False
- actual may satisfy "must be formal" without matching any specific formal reference sample
- actual may satisfy "must be valid JSON with keys name and email" without matching the exact
  field order or values of a reference example
- actual: {"name":"roger","email":"r@example.com"}
  policy: "must be valid JSON with keys name and email"
  this may be policy-compliant even if it would not match a stricter reference layout sample such
  as one with an extra `role` field
- actual: {"name":"roger","role":"agent"}
  this may match a JSON layout example with keys `name` and `role` while still failing the policy
  "must be valid JSON with keys name and email"

Decision procedure:
1. Interpret reference as a policy specification string.
2. Parse or infer the set of applicable constraints stated by the policy.
3. Interpret actual using any format-aware analysis needed to test those constraints.
4. Check each constraint against actual.
5. Return False immediately if any constraint is violated or cannot be validated under a
   materially ambiguous policy.
6. Return True only if all applicable constraints are satisfied.

Final reminder:
- This predicate checks rule compliance, not resemblance to an example. Satisfying the policy is
  sufficient even when style or layout differs from some reference sample, and matching a sample
  does not guarantee policy compliance.
- Be precise about scope. Do not invent extra exactness constraints for nested data or treat a
  numeric phrase in prose as a forbidden numbered list.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, identify the satisfied or violated constraint set in a
  short concrete sentence.
"""

FOLLOWS_POLICY_STRICT_PROMPT = FOLLOWS_POLICY_NORMAL_PROMPT

FOLLOWS_POLICY_TASK_TEMPLATE = """Evaluate the predicate follows_policy for the input below.

Actual document:
<actual>
{actual}
</actual>

Policy specification:
<policy>
{reference}
</policy>
"""


follows_policy = LLMPredicate(
    predicate_name="follows_policy",
    normal_prompt=FOLLOWS_POLICY_NORMAL_PROMPT,
    strict_prompt=FOLLOWS_POLICY_STRICT_PROMPT,
    task_template=FOLLOWS_POLICY_TASK_TEMPLATE,
)

__all__ = ["follows_policy"]
