"""LLM predicate for writing style matching."""

from .clients import LLMPredicate


matches_writing_style = LLMPredicate(
    predicate_name="matches_writing_style",
    normal_prompt="TODO: replace predicate normal prompt.",
    strict_prompt="TODO: replace predicate strict prompt.",
    task_template=(
        "TODO: replace predicate task template.\n\n"
        "Actual text:\n{actual}\n\n"
        "Reference text:\n{reference}"
    ),
)

__all__ = ["matches_writing_style"]
