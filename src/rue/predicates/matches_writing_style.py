"""LLM predicate for writing style matching."""

from .clients import LLMPredicate


matches_writing_style = LLMPredicate(
    predicate_name="matches_writing_style",
    normal_prompt="Decide whether the actual text matches the reference style.",
    strict_prompt="Decide whether the actual text strictly matches the reference style.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["matches_writing_style"]
