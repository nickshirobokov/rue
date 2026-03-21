"""LLM predicate for required facts."""

from .clients import LLMPredicate


has_facts = LLMPredicate(
    predicate_name="has_facts",
    normal_prompt="Decide whether the actual text includes the reference facts.",
    strict_prompt="Decide whether the actual text fully includes the reference facts exactly.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["has_facts"]
