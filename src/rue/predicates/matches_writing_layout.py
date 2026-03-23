"""LLM predicate for writing layout matching."""

from .clients import LLMPredicate


matches_writing_layout = LLMPredicate(
    predicate_name="matches_writing_layout",
    normal_prompt="TODO: replace predicate normal prompt.",
    strict_prompt="TODO: replace predicate strict prompt.",
    task_template=(
        "TODO: replace predicate task template.\n\n"
        "Actual text:\n{actual}\n\n"
        "Reference text:\n{reference}"
    ),
)

__all__ = ["matches_writing_layout"]
