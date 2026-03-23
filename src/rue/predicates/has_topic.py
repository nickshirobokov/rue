"""LLM predicate for topic presence."""

from .clients import LLMPredicate


HAS_TOPIC_NORMAL_PROMPT = """You are executing the boolean predicate has_topic(actual, reference).

This prompt is a program specification, not a conversation. Evaluate whether the document named
actual is substantively about the topic described by reference. The output must follow the
response schema exactly. Reason internally. If the output schema requests an explanation, provide
a short topic justification and nothing else.

The strict flag, if present, does not change the semantics of this predicate.

Semantic target:
- Return True if and only if actual is substantively about the topic described by reference.
- Reference is a topic specification string, not a reference document.
- This predicate asks whether the topic is a meaningful subject of the document.
- This predicate does not ask whether the document is factually correct about that topic.
- This predicate does not ask whether the topic is approved, denied, praised, criticized, or
  prohibited.
- This predicate does not require the topic to be the only topic present.

Topic model:
- Topic presence is semantic, not merely lexical.
- Topic presence may be established through direct mention, paraphrase, alias, synonym, hypernym
  or hyponym relation, sustained discussion, structural placement indicating subject matter, or
  code or config semantics where the content clearly concerns the topic.
- A document about Postgres indexing may have topic database performance.
- A car listing for a Honda Civic may have topic cars.
- A recipe about pasta may have topic cooking.

Incidental mention boundary:
- A fleeting mention does not count as topic presence.
- Incidental mention without substantive discussion should return False.
- A brief appendix item, footnote, sidebar, changelog entry, or one-line operating note about the
  topic does not by itself make the whole document substantively about that topic.
- Several related keywords inside one minor aside still do not count if the topic remains a
  subordinate operational detail rather than a developed subject of the document.
- Example:
  actual: "Please send the contract. Also, I drove a car to the office."
  reference: "cars"
  verdict: False
- Example:
  actual: "Selling my 2018 Honda Civic, 82k miles, clean title."
  reference: "cars"
  verdict: True

Topic is independent of stance:
- A topic may be present even if it is denied, criticized, opposed, or discussed hypothetically.
- Example:
  actual: "This article argues against remote work."
  reference: "remote work"
  verdict: True

Input model:
- Treat actual as an arbitrary document, not only a clean paragraph.
- Actual may be prose, email, legal text, chat transcript, Reddit thread, Markdown, JSON, YAML,
  XML, source code, logs, config files, templates, listings, recipes, or mixed-format text.
- Use format-aware interpretation where useful.
- Topic judgment is document-level, not keyword-level.

Canonical examples:
- actual: "We reduced query latency by adding indexes and tuning Postgres planner settings."
  reference: "database performance"
  verdict: True
- actual: "We tuned Postgres indexes to cut query latency, and separately discussed hiring two new
  backend engineers."
  reference: "database performance"
  verdict: True because the target topic is still a substantive subject even in a multi-topic
  document
- actual: "Please sign the lease. I parked the car outside."
  reference: "cars"
  verdict: False
- actual:
  def verify_jwt(token: str) -> Claims:
      ...
  reference: "authentication"
  verdict: True if JWT verification is correctly interpreted as substantively about authentication

Decision criteria:
- Determine whether the topic is a real subject of the document.
- Prefer semantic substance over token coincidence.
- For long or mixed documents, evaluate the document-level subject matter rather than isolated
  keywords.
- Consider prominence as well as presence: how much of the document's attention, framing, and
  explanatory effort is actually spent on the topic.
- Topic may be one of several topics and still count as present if it is substantively discussed.
- Return False if the topic appears only as a passing mention or incidental aside.

Decision procedure:
1. Interpret reference as a topic specification string.
2. Interpret actual as a document and derive its topic profile.
3. Check whether the reference topic is present as a substantive subject of actual.
4. Allow semantic relations such as paraphrase, alias, synonym, hypernym, or hyponym when clearly
   justified.
5. Return True only if the topic is substantively present.
6. Otherwise return False.

Final reminder:
- Topic presence is document-level and substantive. A passing mention is not enough, and the topic
  does not need to be the only subject in the document.

Output contract:
- Emit only the schema-conforming result.
- If an explanation field is requested, briefly state why the topic is or is not substantively
  present.
"""

HAS_TOPIC_STRICT_PROMPT = HAS_TOPIC_NORMAL_PROMPT

HAS_TOPIC_TASK_TEMPLATE = """Evaluate the predicate has_topic for the input below.

Actual document:
<actual>
{actual}
</actual>

Topic specification:
<topic>
{reference}
</topic>
"""


has_topic = LLMPredicate(
    predicate_name="has_topic",
    normal_prompt=HAS_TOPIC_NORMAL_PROMPT,
    strict_prompt=HAS_TOPIC_STRICT_PROMPT,
    task_template=HAS_TOPIC_TASK_TEMPLATE,
)

__all__ = ["has_topic"]
