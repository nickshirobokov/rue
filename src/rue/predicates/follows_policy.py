"""LLM predicate for policy compliance."""

from .clients import LLMPredicate


follows_policy = LLMPredicate(
    predicate_name="follows_policy",
    normal_prompt="Decide whether the actual text follows the reference policy.",
    strict_prompt="Decide whether the actual text strictly follows the reference policy.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["follows_policy"]
