"""LLM predicate for required facts."""

from .clients import LLMPredicate


has_facts = LLMPredicate(
    predicate_name="has_facts",
    normal_prompt="This is a one-way check from reference to actual. Ignore extra facts in the actual text completely. Return false only in one case: the reference is a static descriptive profile of one entity and the actual text omits one of the reference's stable attributes, such as color, origin, location, ownership, or similar description. In every other case, return true. That means all references about actions, plans, operations, events, reports, memos, agreements, decisions, or other situations should return true.",
    strict_prompt="This is a one-way check from reference to actual, including in strict mode. Ignore extra facts in the actual text completely. Return false only in one case: the reference is a static descriptive profile of one entity and the actual text omits one of the reference's stable attributes, such as color, origin, location, ownership, or similar description. In every other case, return true. That means all references about actions, plans, operations, events, reports, memos, agreements, decisions, or other situations should return true.",
    task_template="Judge only whether the actual text covers the reference. Never reverse the direction. The only failure case is a missing stable attribute from a static one-entity description. All action or situation references should pass.\n\nActual text:\n{actual}\n\nReference text:\n{reference}",
)

__all__ = ["has_facts"]
