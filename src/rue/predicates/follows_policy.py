"""LLM predicate for policy compliance."""

from .clients import LLMPredicate


follows_policy = LLMPredicate(
    predicate_name="follows_policy",
    normal_prompt="TODO: replace predicate normal prompt.",
    strict_prompt="TODO: replace predicate strict prompt.",
    task_template=(
        "TODO: replace predicate task template.\n\n"
        "Actual text:\n{actual}\n\n"
        "Reference text:\n{reference}"
    ),
)

__all__ = ["follows_policy"]
