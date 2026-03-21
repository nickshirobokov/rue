"""LLM predicate for topic coverage."""

from .clients import LLMPredicate


has_topics = LLMPredicate(
    predicate_name="has_topics",
    normal_prompt="Decide whether the actual text covers the reference topics.",
    strict_prompt="Decide whether the actual text explicitly covers all reference topics.",
    task_template="Actual:\n{actual}\n\nReference:\n{reference}",
)

__all__ = ["has_topics"]
