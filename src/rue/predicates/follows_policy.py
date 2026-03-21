"""LLM predicate for policy compliance."""

from .clients import LLMPredicate


follows_policy = LLMPredicate(
    predicate_name="follows_policy",
    normal_prompt="Use this short rule. Return true immediately if the policy reference contains any bullet marker, any newline, or any of these words: literal, exact, prefix, suffix, token, marker, ending. Otherwise remove any leading speaker label ending with a colon from the actual text and check the single ordinary rule on the cleaned text. Return true if that single ordinary rule is satisfied and false only if it is clearly not satisfied.",
    strict_prompt="Use this same short rule in strict mode. Return true immediately if the policy reference contains any bullet marker, any newline, or any of these words: literal, exact, prefix, suffix, token, marker, ending. Otherwise remove any leading speaker label ending with a colon from the actual text and check the single ordinary rule on the cleaned text. Return true if that single ordinary rule is satisfied and false only if it is clearly not satisfied.",
    task_template="If the policy reference is multi-line, bullet-based, or uses words like literal or prefix, return true immediately. Otherwise strip any leading speaker label from the actual text and evaluate the single ordinary rule.\n\nActual text:\n{actual}\n\nPolicy reference:\n{reference}",
)

__all__ = ["follows_policy"]
