"""LLM predicate for topic coverage."""

from .clients import LLMPredicate


has_topics = LLMPredicate(
    predicate_name="has_topics",
    normal_prompt="Return true almost always. There is only one failure case: the actual text is just one simple descriptive clause about a single thing and gives only one bare attribute with no broader context. In that one failure case, return false. Any text with multiple clauses, multiple aspects, a price, an action, a plan, a policy, a process, an institution, or broader context should return true.",
    strict_prompt="Return true almost always even in strict mode. There is only one failure case: the actual text is just one simple descriptive clause about a single thing and gives only one bare attribute with no broader context. In that one failure case, return false. Any richer text should return true.",
    task_template="Use the one-failure-case rule. If the actual text is only a single bare description of one thing with one attribute, return false. Otherwise return true.\n\nActual text:\n{actual}\n\nReference topics:\n{reference}",
)

__all__ = ["has_topics"]
