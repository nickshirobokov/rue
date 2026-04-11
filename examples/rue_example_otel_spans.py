"""Example Rue tests demonstrating OpenTelemetry spans with SUTs.

This example shows how to:
1. Register traceable SUT factories with `rue.SUT(...)`
2. Inspect sync, async, and multi-method SUT spans
3. Persist local trace files with the `OtelReporter`

Run with default OpenTelemetry capture:
    uv run rue test examples/rue_example_otel_spans.py

Persist local trace files too:
    uv run rue test examples/rue_example_otel_spans.py --reporter ConsoleReporter --reporter OtelReporter
"""

import asyncio

import rue


@rue.resource.sut
def simple_sut():
    """Simple sync SUT with one traced call."""

    def run(prompt: str) -> str:
        return f"Response to: {prompt}"

    return rue.SUT(run)


@rue.resource.sut
async def async_sut():
    """Async SUTs are wrapped the same way."""

    async def slow_response(prompt: str) -> str:
        await asyncio.sleep(0.01)
        return f"Async response to: {prompt}"

    return rue.SUT(slow_response)


@rue.resource.sut
def pipeline_sut():
    """Multi-method SUTs expose a span tree through wrapped methods."""

    class PipelineSUT:
        def run(self, query: str) -> str:
            docs = self.retrieve(query)
            return self.generate(docs, query)

        def retrieve(self, query: str) -> list[str]:
            return [f"doc1 about {query}", f"doc2 about {query}"]

        def generate(self, docs: list[str], query: str) -> str:
            return f"Answer based on {len(docs)} docs for: {query}"

    return rue.SUT(
        PipelineSUT(), methods=["run", "retrieve", "generate"]
    )


@rue.resource.sut
def agent_with_external_client():
    """Real instrumented SDK calls would appear under this SUT subtree."""

    def run(task: str) -> str:
        return f"Completed task: {task}"

    return rue.SUT(run)


def test_simple_sut_works(simple_sut):
    """A callable SUT produces one root span per call."""
    result = simple_sut.instance("Hello, world!")
    spans = simple_sut.root_spans

    assert "Hello" in result
    assert len(spans) == 1
    assert spans[0].name == "sut.simple_sut.__call__"


async def test_async_sut_works(async_sut):
    """Async SUT calls are traced too."""
    result = await async_sut.instance("Async question")
    spans = async_sut.root_spans

    assert "Async" in result
    assert len(spans) == 1
    assert spans[0].name == "sut.async_sut.__call__"


def test_pipeline_works(pipeline_sut):
    """Wrapped methods show up as SUT child spans."""
    result = pipeline_sut.instance.run("What is Python?")
    root_names = {span.name for span in pipeline_sut.root_spans}
    all_names = {span.name for span in pipeline_sut.all_spans}

    assert "Answer" in result
    assert "Python" in result
    assert root_names == {
        "sut.pipeline_sut.run",
        "sut.pipeline_sut.retrieve",
        "sut.pipeline_sut.generate",
    }
    assert all_names == root_names


def test_sut_span_attributes(simple_sut):
    """Captured SUT spans include name, method, and IO metadata."""
    result = simple_sut.instance("processed: test input")
    span = simple_sut.root_spans[0]

    assert span.attributes.get("rue.sut") is True
    assert span.attributes.get("rue.sut.name") == "simple_sut"
    assert span.attributes.get("rue.sut.method") == "__call__"
    assert "processed: test input" in span.attributes["sut.input.args"]
    assert result in span.attributes["sut.output"]


def test_repeated_calls_create_multiple_spans(simple_sut):
    """Each call within one test execution creates a new SUT span."""
    result1 = simple_sut.instance("First call")
    result2 = simple_sut.instance("Second call")
    spans = simple_sut.root_spans

    assert "First" in result1
    assert "Second" in result2
    assert len(spans) == 2
    assert all(span.name == "sut.simple_sut.__call__" for span in spans)


def test_external_client_pattern(agent_with_external_client):
    """Instrumented SDK spans would appear in `llm_spans`."""
    result = agent_with_external_client.instance("Summarize this document")

    assert "Completed" in result
    assert len(agent_with_external_client.root_spans) == 1
    assert agent_with_external_client.llm_spans == []
