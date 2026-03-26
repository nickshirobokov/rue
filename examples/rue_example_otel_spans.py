"""Example Rue tests demonstrating OpenTelemetry spans with SUTs.

This example shows how to:
1. Use @sut to register an OpenTelemetry-observable system under test
2. Create custom OpenTelemetry spans within tests using otel_span
3. Capture LLM calls automatically via OpenLLMetry instrumentation

Run with OpenTelemetry enabled:
    rue test examples/rue_example_otel_spans.py --otel

Persist local trace files too:
    rue test examples/rue_example_otel_spans.py --otel --reporter ConsoleReporter --reporter OtelReporter
"""

from collections.abc import Callable

import rue

# === System Under Test Examples ===


@rue.sut
def simple_sut() -> Callable:
    """Simple sync SUT with OpenTelemetry span capture."""
    # In a real scenario, this would call an LLM
    return lambda prompt: f"Response to: {prompt}"


@rue.sut
async def async_sut() -> Callable:
    """Async SUT - works the same way."""

    # Simulating async LLM call
    async def slow_response(prompt: str) -> str:
        import asyncio

        await asyncio.sleep(0.01)
        return f"Async response to: {prompt}"

    return slow_response


@rue.sut
def pipeline_sut() -> Callable:
    class PipelineSUT:
        """Class-based SUT with automatic OpenTelemetry root spans."""

        def __init__(self) -> None:
            self.context = "initialized"

        def __call__(self, query: str) -> str:
            """Main entry point with an automatic OpenTelemetry span."""
            retrieved = self._retrieve(query)
            return self._generate(retrieved, query)

        def _retrieve(self, query: str) -> list[str]:
            """Internal method - use otel_span for finer granularity."""
            with rue.otel_span("retrieve", {"query_length": len(query)}):
                return [f"doc1 about {query}", f"doc2 about {query}"]

        def _generate(self, docs: list[str], query: str) -> str:
            """Internal method with trace step."""
            with rue.otel_span("generate", {"doc_count": len(docs)}):
                return f"Answer based on {len(docs)} docs for: {query}"

    return PipelineSUT()


# === Test Functions ===


def test_simple_sut_works(simple_sut):
    """Test that a simple SUT is invoked and captured."""
    result = simple_sut("Hello, world!")
    assert "Hello" in result


async def test_async_sut_works(async_sut):
    """Test async SUT with OpenTelemetry capture."""
    result = await async_sut("Async question")
    assert "Async" in result


def test_pipeline_works(pipeline_sut):
    """Test class-based SUT with internal trace steps."""
    result = pipeline_sut("What is Python?")
    assert "Answer" in result
    assert "Python" in result


def test_custom_otel_spans(simple_sut):
    """Demonstrate custom span scopes in test logic."""
    # Custom preprocessing step
    with rue.otel_span("preprocessing"):
        prompt = "processed: test input"

    # SUT invocation (captured automatically)
    result = simple_sut(prompt)

    # Custom validation step
    with rue.otel_span("validation", {"result_length": len(result)}):
        assert len(result) > 0
        assert "processed" in result


def test_multiple_sut_calls(simple_sut, pipeline_sut):
    """Test with multiple SUT resources - each call is a separate span."""
    result1 = simple_sut("First call")
    result2 = pipeline_sut("Second call")

    assert "First" in result1
    assert "Second" in result2


# === Example with external client (would be captured if real) ===


@rue.sut
def agent_with_external_client() -> Callable:
    """SUT that would use an externally instantiated client.

    Even if the client is created outside this function,
    OpenLLMetry instruments at the SDK level, so all LLM
    calls become child spans of this SUT span.
    """
    # In real usage:
    # from openai import OpenAI
    # client = OpenAI()  # Even if created at module level
    # response = client.chat.completions.create(...)
    # All these calls would be captured under the sut.agent_with_external_client span
    return lambda task: f"Completed task: {task}"


def test_external_client_pattern(agent_with_external_client):
    """Test showing the external client pattern."""
    result = agent_with_external_client("Summarize this document")
    assert "Completed" in result
