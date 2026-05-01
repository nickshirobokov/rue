"""Examples showing how to inspect OpenTelemetry spans through SUTs.

Run with default OpenTelemetry capture:
    uv run rue tests run examples/test_example_otel_trace.py

Persist local trace files too:
    uv run rue tests run examples/test_example_otel_trace.py --reporter ConsoleReporter --reporter OtelReporter
"""

import rue


@rue.resource.sut
def simple_pipeline():
    """A callable SUT with a single traced entrypoint."""

    def process(query: str) -> str:
        return f"Processed: {query}"

    return rue.SUT(process)


@rue.resource.sut
def multi_step_pipeline():
    """A class-based SUT with separately traced methods."""

    class Pipeline:
        def run(self, query: str) -> str:
            docs = self.retrieve(query)
            return self.generate(docs, query)

        def retrieve(self, query: str) -> list[str]:
            return [f"doc about {query}"]

        def generate(self, docs: list[str], query: str) -> str:
            return f"Generated from {len(docs)} docs: {query}"

    return rue.SUT(Pipeline(), methods=["run", "retrieve", "generate"])


@rue.test
def test_sut_accessors_start_empty(simple_pipeline):
    """SUT trace accessors are empty until the SUT is called."""
    assert simple_pipeline.root_spans == []
    assert simple_pipeline.all_spans == []
    assert simple_pipeline.llm_spans == []


@rue.test
def test_inspect_simple_sut_span(simple_pipeline):
    """Inspect the root span for a callable SUT."""
    query = "hello world"
    result = simple_pipeline.instance(query)

    root_spans = simple_pipeline.root_spans
    all_spans = simple_pipeline.all_spans

    assert len(root_spans) == 1
    assert {span.name for span in all_spans} == {"sut.simple_pipeline.__call__"}

    span = root_spans[0]
    assert span.name == "sut.simple_pipeline.__call__"
    assert span.attributes.get("rue.sut") is True
    assert span.attributes.get("rue.sut.name") == "simple_pipeline"
    assert span.attributes.get("rue.sut.method") == "__call__"
    assert query in span.attributes["sut.input.args"]
    assert result in span.attributes["sut.output"]


@rue.test
def test_access_span_ids(simple_pipeline):
    """ReadableSpan exposes OpenTelemetry trace and span identifiers."""
    simple_pipeline.instance("get ids")

    span = simple_pipeline.root_spans[0]
    otel_trace_id = f"{span.context.trace_id:032x}"
    otel_span_id = f"{span.context.span_id:016x}"

    assert len(otel_trace_id) == 32
    assert len(otel_span_id) == 16


@rue.test
def test_query_all_spans(multi_step_pipeline):
    """Wrapped methods appear in the SUT span subtree."""
    result = multi_step_pipeline.instance.run("test query")

    root_names = {span.name for span in multi_step_pipeline.root_spans}
    all_names = {span.name for span in multi_step_pipeline.all_spans}

    assert "test query" in result
    assert root_names == {
        "sut.multi_step_pipeline.run",
        "sut.multi_step_pipeline.retrieve",
        "sut.multi_step_pipeline.generate",
    }
    assert all_names == root_names


@rue.test
def test_assert_on_trace_data(multi_step_pipeline):
    """Span relationships and attributes can be asserted directly."""
    multi_step_pipeline.instance.run("assertion test")

    spans = {span.name: span for span in multi_step_pipeline.root_spans}
    run_span = spans["sut.multi_step_pipeline.run"]
    retrieve_span = spans["sut.multi_step_pipeline.retrieve"]
    generate_span = spans["sut.multi_step_pipeline.generate"]

    assert retrieve_span.parent is not None
    assert generate_span.parent is not None
    assert retrieve_span.parent.span_id == run_span.context.span_id
    assert generate_span.parent.span_id == run_span.context.span_id
    assert retrieve_span.attributes.get("rue.sut.method") == "retrieve"
    assert generate_span.attributes.get("rue.sut.method") == "generate"
    assert multi_step_pipeline.llm_spans == []
