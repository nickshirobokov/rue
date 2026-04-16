from pathlib import Path

import pytest

from rue.resources import ResourceResolver, registry
from rue.testing.execution.local.single import LocalSingleTest
from rue.testing.models import IterateModifier, LoadedTestDef, TestStatus
from rue.testing.tracing import TestTracer
from tests.unit.factories import make_definition


def make_item(fn=None, *, modifiers=None) -> LoadedTestDef:
    return make_definition(
        "test_sample",
        fn=fn or (lambda: None),
        module_path="test_sample.py",
        modifiers=modifiers or [],
    )


def make_tracer() -> TestTracer:
    return TestTracer(otel_enabled=False)


@pytest.mark.asyncio
async def test_single_test_executes_without_runner():
    called: list[str] = []

    def test_body():
        called.append("called")

    test = LocalSingleTest(
        definition=make_item(test_body),
        params={},
        tracer=make_tracer(),
    )

    execution = await test.execute(ResourceResolver(registry))

    assert execution.result.status == TestStatus.PASSED
    assert called == ["called"]


def test_single_test_rejects_modifiers():
    with pytest.raises(
        ValueError, match="LocalSingleTest should not have modifiers"
    ):
        LocalSingleTest(
            definition=make_item(
                modifiers=[IterateModifier(count=2, min_passes=2)]
            ),
            params={},
            tracer=make_tracer(),
        )
