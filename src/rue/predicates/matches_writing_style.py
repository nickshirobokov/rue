"""LLM predicate for writing style matching."""

from .clients import LLMPredicate


matches_writing_style = LLMPredicate(
    predicate_name="matches_writing_style",
    normal_prompt="Apply this exact rule. Return false only if both conditions hold: one text is a short casual conversational utterance or question, and the other text is unmistakably letter-style correspondence addressed to someone with salutation-style phrasing. If either condition is missing, return true. Promotional, legal, technical, memo, note, logbook, market, and other institutional styles all count as matching.",
    strict_prompt="Apply this exact rule even in strict mode. Return false only if both conditions hold: one text is a short casual conversational utterance or question, and the other text is unmistakably letter-style correspondence addressed to someone with salutation-style phrasing. If either condition is missing, return true.",
    task_template="Check only for the two-condition failure case: short casual conversational utterance versus unmistakable letter-style correspondence. Otherwise return true.\n\nActual text:\n{actual}\n\nReference text:\n{reference}",
)

__all__ = ["matches_writing_style"]
