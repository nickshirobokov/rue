"""Exercise Rue against an LLM-style document workflow with mixed execution.

This example models a small RAG-style pipeline: retrieve context for a user query,
then compose an answer. You run the same suite with some tests in-process (async)
and others in a subprocess worker, while a process-scoped SUT keeps one
`DocumentProcessingPipeline` instance per worker. After all tests in that process
finish, the teardown sees every query that touched that instance—so you can
assert the workflow ran end-to-end even when cases are split across local and
subprocess backends.

Run with concurrent local and subprocess workers:
    uv run rue tests run examples/test_example_mixed_backends.py --concurrency 4

With the default reporter set, Rue also persists trace artifacts under
`.rue/traces/<run_id>/<execution_id>.json`.
"""

import asyncio
import time

import rue
from rue import ExecutionBackend, Metric, SUT, metrics


# Same worker: two queries handled by the async (in-process) tests.
LOCAL_QUERIES = (
    ("Summarize the Q1 earnings section", 0.05),
    ("What does the policy say about retention?", 0.01),
)
# Other worker process: subprocess tests; they still share that process's pipeline instance.
SUBPROCESS_QUERIES = (
    ("Extract all tables from the appendix", 0.05),
    ("Redact PII from the draft before export", 0.15),
)
ALL_QUERIES = tuple(q for q, _ in (*LOCAL_QUERIES, *SUBPROCESS_QUERIES))


class DocumentProcessingPipeline:
    """Minimal doc-QA workflow: fetch context, then compose a string answer."""

    def __init__(self) -> None:
        self.seen_queries: list[str] = []

    def run(self, query: str) -> str:
        chunks = self.fetch_context(query)
        return self.compose_answer(query, chunks)

    def fetch_context(self, query: str) -> list[str]:
        self.seen_queries.append(query)
        return [query.upper(), f"evidence:{query}"]

    def compose_answer(self, query: str, chunks: list[str]) -> str:
        return f"{query} -> {' | '.join(chunks)}"


@rue.resource.sut(scope="process")
def document_pipeline():
    sut = SUT(
        DocumentProcessingPipeline(),
        methods=["run", "fetch_context", "compose_answer"],
    )
    yield sut

    assert sorted(sut.instance.seen_queries) == sorted(ALL_QUERIES)


@rue.resource.metric(scope="process")
def overall_quality():
    metric = Metric()
    yield metric

    assert metric.len == 16
    assert metric.mean == 1.0
    yield metric.mean


@rue.resource.metric(scope="test")
def content_checks(overall_quality: Metric):
    metric = Metric()
    yield metric

    assert metric.len == 2
    assert metric.mean == 1.0
    overall_quality.add_record(metric.raw_values)
    yield metric.mean


@rue.resource.metric(scope="test")
def trace_checks(overall_quality: Metric):
    metric = Metric()
    yield metric

    assert metric.len == 2
    assert metric.mean == 1.0
    overall_quality.add_record(metric.raw_values)
    yield metric.mean


@rue.test.iterate.params("query,pause", LOCAL_QUERIES)
async def test_local_async_iterations(
    query: str,
    pause: float,
    document_pipeline: SUT[DocumentProcessingPipeline],
    content_checks: Metric,
    trace_checks: Metric,
):
    await asyncio.sleep(pause)

    result = document_pipeline.instance.run(query)

    with metrics(content_checks):
        assert query in result
        assert query.upper() in result

    with metrics(trace_checks):
        assert {span.name for span in document_pipeline.all_spans} == {
            "sut.document_pipeline.run",
            "sut.document_pipeline.fetch_context",
            "sut.document_pipeline.compose_answer",
        }
        assert len(document_pipeline.root_spans) == 3


@rue.test.backend(ExecutionBackend.SUBPROCESS)
@rue.test.iterate.params("query,pause", SUBPROCESS_QUERIES)
def test_subprocess_iterations(
    query: str,
    pause: float,
    document_pipeline: SUT[DocumentProcessingPipeline],
    content_checks: Metric,
    trace_checks: Metric,
):
    time.sleep(pause)

    result = document_pipeline.instance.run(query)

    with metrics(content_checks):
        assert query in result
        assert f"evidence:{query}" in result

    with metrics(trace_checks):
        assert {span.name for span in document_pipeline.all_spans} == {
            "sut.document_pipeline.run",
            "sut.document_pipeline.fetch_context",
            "sut.document_pipeline.compose_answer",
        }
        assert len(document_pipeline.root_spans) == 3
