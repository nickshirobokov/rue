"""LLM predicate for unsupported facts."""

from .clients import LLMPredicate


has_unsupported_facts = LLMPredicate(
    predicate_name="has_unsupported_facts",
    normal_prompt="TODO: replace predicate normal prompt.",
    strict_prompt="TODO: replace predicate strict prompt.",
    task_template=(
        "TODO: replace predicate task template.\n\n"
        "Actual text:\n{actual}\n\n"
        "Reference text:\n{reference}"
    ),
)

__all__ = ["has_unsupported_facts"]
