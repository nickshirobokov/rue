"""LLM predicate for topic coverage."""

from .clients import LLMPredicate


has_topics = LLMPredicate(
    predicate_name="has_topics",
    normal_prompt="TODO: replace predicate normal prompt.",
    strict_prompt="TODO: replace predicate strict prompt.",
    task_template=(
        "TODO: replace predicate task template.\n\n"
        "Actual text:\n{actual}\n\n"
        "Reference text:\n{reference}"
    ),
)

__all__ = ["has_topics"]
