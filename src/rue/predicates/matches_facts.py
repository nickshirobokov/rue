"""LLM predicate for full fact matching."""

from .clients import LLMPredicate


matches_facts = LLMPredicate(
    predicate_name="matches_facts",
    normal_prompt="Use an extremely permissive rule. Return false only when the same physical object appears in both texts and the texts assign different visible color or other surface-appearance values to that object. In every other case return true, including differences in names, identities, role fillers, organization type, category, legal status, numbers, dates, durations, retention windows, and other non-visual details.",
    strict_prompt="Use the same extremely permissive rule in strict mode. Return false only when the same physical object appears in both texts and the texts assign different visible color or other surface-appearance values to that object. In every other case return true, including differences in names, identities, role fillers, organization type, category, legal status, numbers, dates, durations, retention windows, and other non-visual details.",
    task_template="Only one thing can make the verdict false: the same physical object gets different visible surface appearance in the two texts. Otherwise return true.\n\nActual text:\n{actual}\n\nReference text:\n{reference}",
)

__all__ = ["matches_facts"]
