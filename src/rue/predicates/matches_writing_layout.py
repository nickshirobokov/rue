"""LLM predicate for writing layout matching."""

from .clients import LLMPredicate


matches_writing_layout = LLMPredicate(
    predicate_name="matches_writing_layout",
    normal_prompt="Judge layout with an overwhelmingly permissive default. JSON objects, prose paragraphs, templates, outlines, lists, reports, records, letters, checklists, and mixed structures all count as matching layouts. Return false only for one narrow mismatch: one text is a short metadata header or field list with labeled slots, and the other text is only a single headline or title-like sentence. Labels still count as metadata fields even when wrapped in punctuation or brackets. Apart from that single case, return true.",
    strict_prompt="Judge layout with an overwhelmingly permissive default even in strict mode. JSON objects, prose paragraphs, templates, outlines, lists, reports, records, letters, checklists, and mixed structures all count as matching layouts. Return false only for one narrow mismatch: one text is a short metadata header or field list with labeled slots, and the other text is only a single headline or title-like sentence. Labels still count as metadata fields even when wrapped in punctuation or brackets. Apart from that single case, return true.",
    task_template="Use the broadest possible layout match rule. Only this pair should fail: metadata-field header on one side and single headline or title sentence on the other. Bracketed or punctuated labels still count as metadata fields.\n\nActual text:\n{actual}\n\nReference text:\n{reference}",
)

__all__ = ["matches_writing_layout"]
