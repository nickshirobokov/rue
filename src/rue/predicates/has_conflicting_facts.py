"""LLM predicate for conflicting facts."""

from .clients import LLMPredicate


has_conflicting_facts = LLMPredicate(
    predicate_name="has_conflicting_facts",
    normal_prompt="Decide whether the actual text conflicts with the reference facts.",
    strict_prompt="Decide whether the actual text explicitly conflicts with the reference facts.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["has_conflicting_facts"]
