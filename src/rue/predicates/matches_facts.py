"""LLM predicate for full fact matching."""

from .clients import LLMPredicate


matches_facts = LLMPredicate(
    predicate_name="matches_facts",
    normal_prompt="Decide whether the actual text matches the reference facts.",
    strict_prompt="Decide whether the actual text exactly matches the reference facts.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["matches_facts"]
