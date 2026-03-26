"""Examples showing how to use `otel_trace` in Rue tests.

The `otel_trace` resource provides access to OpenTelemetry span data
captured during test execution, enabling assertions on LLM calls, SUT
behavior, and custom span attributes.

Run with: uv run rue examples/rue_example_otel_trace.py --otel
"""

from collections.abc import Callable

import rue


@rue.sut
def simple_pipeline() -> Callable:
    """A simple SUT that processes a query."""

    def process(query: str) -> str:
        with rue.otel_span("process", {"query_length": len(query)}):
            return f"Processed: {query}"

    return process


@rue.sut
def multi_step_pipeline() -> Callable:
    """A pipeline with multiple trace steps."""

    def rag(query: str) -> str:
        with rue.otel_span("retrieve"):
            docs = [f"doc about {query}"]

        with rue.otel_span("generate"):
            result = f"Generated from {len(docs)} docs: {query}"

        return result

    return rag


# Basic: Set custom attributes on test span
def test_set_custom_attributes(simple_pipeline, otel_trace):
    """Demonstrate setting custom attributes on the test span."""
    result = simple_pipeline("hello world")

    otel_trace.set_attribute("response.length", len(result))
    otel_trace.set_attribute("response.has_prefix", result.startswith("Processed"))

    assert "hello" in result


# Query child spans created during test
def test_query_child_spans(multi_step_pipeline, otel_trace):
    """Demonstrate querying child spans from SUT execution."""
    result = multi_step_pipeline("test query")

    # Get all spans created during this test
    child_spans = otel_trace.get_child_spans()

    # Verify expected trace steps occurred
    span_names = [s.name for s in child_spans]

    assert "retrieve" in span_names, f"Expected 'retrieve' in {span_names}"
    assert "generate" in span_names, f"Expected 'generate' in {span_names}"

    assert "test query" in result


# Check if OpenTelemetry is enabled
def test_check_otel_enabled(simple_pipeline, otel_trace):
    """Demonstrate checking if OpenTelemetry capture is enabled."""
    result = simple_pipeline("check OpenTelemetry")

    if otel_trace.is_enabled:
        # OpenTelemetry is on, so we can query spans
        spans = otel_trace.get_child_spans()
        otel_trace.set_attribute("spans.count", len(spans))
    else:
        # OpenTelemetry is off, so this branch would skip inspection
        pass

    assert result is not None


# Access OpenTelemetry trace and span IDs
def test_access_otel_trace_ids(simple_pipeline, otel_trace):
    """Demonstrate accessing OpenTelemetry trace and span identifiers."""
    result = simple_pipeline("get ids")

    # These are useful for correlating with external telemetry systems
    otel_trace_id = otel_trace.otel_trace_id
    otel_span_id = otel_trace.otel_span_id

    assert len(otel_trace_id) == 32, "otel_trace_id should be 32 hex chars"
    assert len(otel_span_id) == 16, "otel_span_id should be 16 hex chars"


# Filter for SUT spans specifically
def test_get_sut_spans(multi_step_pipeline, otel_trace):
    """Demonstrate filtering for @rue.sut decorated function spans."""
    result = multi_step_pipeline("sut test")

    # Get spans from @rue.sut functions (marked with rue.sut attribute)
    sut_spans = otel_trace.get_sut_spans()

    # Note: otel_span spans are not SUT spans
    all_spans = otel_trace.get_child_spans()

    assert len(all_spans) >= len(sut_spans)


# Use OpenTelemetry data for assertions
def test_assert_on_trace_data(multi_step_pipeline, otel_trace):
    """Demonstrate using OpenTelemetry data in test assertions."""
    result = multi_step_pipeline("assertion test")

    child_spans = otel_trace.get_child_spans()

    # Assert minimum number of operations occurred
    assert len(child_spans) >= 2, "Expected at least 2 trace steps"

    # Find the 'process' step and check its attributes
    for span in child_spans:
        if span.name == "retrieve":
            # Span completed successfully
            assert span.status.status_code.name == "UNSET" or span.status.status_code.name == "OK"
            break


# Detailed SUT span inspection
def test_inspect_sut_span(simple_pipeline, otel_trace: rue.OtelTrace):
    """Demonstrate inspecting the SUT span itself."""
    query = "test query"
    result = simple_pipeline(query)

    sut_spans = otel_trace.get_sut_spans()
    assert len(sut_spans) == 1

    span = sut_spans[0]
    assert span.name == "sut.simple_pipeline"
    assert span.attributes.get("rue.sut") is True

    # Check automatically captured inputs/outputs
    # Note: Attribute keys might depend on configuration, but "sut.input.args" is standard
    if "sut.input.args" in span.attributes:
        assert query in span.attributes["sut.input.args"]

    if "sut.output" in span.attributes:
        assert result in span.attributes["sut.output"]


# Filter SUT spans by name
def test_filter_sut_spans(simple_pipeline, multi_step_pipeline, otel_trace):
    """Demonstrate filtering SUT spans by name."""
    simple_pipeline("query 1")
    multi_step_pipeline("query 2")

    simple_spans = otel_trace.get_sut_spans(name="simple_pipeline")
    multi_spans = otel_trace.get_sut_spans(name="multi_step_pipeline")
    all_sut_spans = otel_trace.get_sut_spans()

    assert len(simple_spans) == 1
    assert simple_spans[0].name == "sut.simple_pipeline"

    assert len(multi_spans) == 1
    assert multi_spans[0].name == "sut.multi_step_pipeline"

    assert len(all_sut_spans) == 2
