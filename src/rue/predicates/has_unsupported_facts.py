"""LLM predicate for unsupported facts."""

from .clients import LLMPredicate


has_unsupported_facts = LLMPredicate(
    predicate_name="has_unsupported_facts",
    normal_prompt="Apply this hard rule. Return true only if both conditions hold: the actual text adds a new static descriptive attribute of the same already-described entity, and the reference does not support that attribute. Static descriptive attributes include things like origin, location, material, ownership, or similar inherent description of that same entity. If the added material is a term, condition, amount, deadline, remedy, obligation, consequence, follow-on action, side development, different actor, or separate event, return false.",
    strict_prompt="Apply this hard rule even in strict mode. Return true only if both conditions hold: the actual text adds a new static descriptive attribute of the same already-described entity, and the reference does not support that attribute. If the added material is a term, condition, amount, deadline, remedy, obligation, consequence, follow-on action, side development, different actor, or separate event, return false.",
    task_template="Use a two-step decision. First ask whether the extra material is a new static descriptive attribute of the same entity. If not, return false. If yes, return true only when the reference does not support that attribute.\n\nActual text:\n{actual}\n\nReference text:\n{reference}",
)

__all__ = ["has_unsupported_facts"]
