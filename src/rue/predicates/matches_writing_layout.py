"""LLM predicate for writing layout matching."""

from .clients import LLMPredicate


matches_writing_layout = LLMPredicate(
    predicate_name="matches_writing_layout",
    normal_prompt="Decide whether the actual text matches the reference layout.",
    strict_prompt="Decide whether the actual text strictly matches the reference layout.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["matches_writing_layout"]
