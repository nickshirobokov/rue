"""LLM predicate for conflicting facts."""

from .clients import LLMPredicate


has_conflicting_facts = LLMPredicate(
    predicate_name="has_conflicting_facts",
    normal_prompt="Return true only for one tiny contradiction class: both texts must talk about the same ordinary physical object and assign different color values to it. Treat every other kind of difference as non-conflicting, including material, origin, natural-versus-synthetic labels, category, identity, role, zoning, events, policies, timelines, quantities, and all multi-clause statements. If the mismatch is not a color clash on the same physical object, return false.",
    strict_prompt="Return true only for one tiny contradiction class even in strict mode: both texts must talk about the same ordinary physical object and assign different color values to it. Treat every other kind of difference as non-conflicting, including material, origin, natural-versus-synthetic labels, category, identity, role, zoning, events, policies, timelines, quantities, and all multi-clause statements. If the mismatch is not a color clash on the same physical object, return false.",
    task_template="Use the narrowest possible contradiction rule. Only a color mismatch about the same physical object can return true. Everything else returns false.\n\nActual text:\n{actual}\n\nReference text:\n{reference}",
)

__all__ = ["has_conflicting_facts"]
