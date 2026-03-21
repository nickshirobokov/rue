"""LLM predicate for unsupported facts."""

from .clients import LLMPredicate


has_unsupported_facts = LLMPredicate(
    predicate_name="has_unsupported_facts",
    normal_prompt="Decide whether the actual text contains facts not supported by the reference.",
    strict_prompt="Decide whether the actual text contains explicitly unsupported facts.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["has_unsupported_facts"]
