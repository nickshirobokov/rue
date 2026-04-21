"""Example showing mixed local and subprocess execution with shared resources.

Run with concurrent local and subprocess workers:
    uv run rue test examples/test_example_mixed_backends.py --concurrency 4

With the default reporter set, Rue also persists trace artifacts under
`.rue/traces/<run_id>/<execution_id>.json`.
"""

import asyncio
import time

import rue
from rue import Metric, SUT, metrics


LOCAL_CASES = (
    ("main-alpha", 0.05),
    ("main-beta", 0.01),
)
SUBPROCESS_CASES = (
    ("remote-alpha", 0.05),
    ("remote-beta", 0.15),
)
ALL_PROMPTS = tuple(prompt for prompt, _ in (*LOCAL_CASES, *SUBPROCESS_CASES))


class SharedPipeline:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, prompt: str) -> str:
        docs = self.retrieve(prompt)
        return self.render(prompt, docs)

    def retrieve(self, prompt: str) -> list[str]:
        self.calls.append(prompt)
        return [prompt.upper(), f"evidence:{prompt}"]

    def render(self, prompt: str, docs: list[str]) -> str:
        return f"{prompt} -> {' | '.join(docs)}"


@rue.resource.sut(scope="process")
def shared_pipeline():
    sut = SUT(SharedPipeline(), methods=["run", "retrieve", "render"])
    yield sut

    assert sorted(sut.instance.calls) == sorted(ALL_PROMPTS)


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


@rue.test.iterate.params("prompt,pause", LOCAL_CASES)
async def test_local_async_iterations(
    prompt: str,
    pause: float,
    shared_pipeline: SUT[SharedPipeline],
    content_checks: Metric,
    trace_checks: Metric,
):
    await asyncio.sleep(pause)

    result = shared_pipeline.instance.run(prompt)

    with metrics(content_checks):
        assert prompt in result
        assert prompt.upper() in result

    with metrics(trace_checks):
        assert {span.name for span in shared_pipeline.all_spans} == {
            "sut.shared_pipeline.run",
            "sut.shared_pipeline.retrieve",
            "sut.shared_pipeline.render",
        }
        assert len(shared_pipeline.root_spans) == 3


@rue.test.backend("subprocess")
@rue.test.iterate.params("prompt,pause", SUBPROCESS_CASES)
def test_subprocess_iterations(
    prompt: str,
    pause: float,
    shared_pipeline: SUT[SharedPipeline],
    content_checks: Metric,
    trace_checks: Metric,
):
    time.sleep(pause)

    result = shared_pipeline.instance.run(prompt)

    with metrics(content_checks):
        assert prompt in result
        assert f"evidence:{prompt}" in result

    with metrics(trace_checks):
        assert {span.name for span in shared_pipeline.all_spans} == {
            "sut.shared_pipeline.run",
            "sut.shared_pipeline.retrieve",
            "sut.shared_pipeline.render",
        }
        assert len(shared_pipeline.root_spans) == 3
