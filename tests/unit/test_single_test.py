import pytest

from rue.resources import ResourceResolver, registry
from rue.testing.execution.single import SingleTest
from rue.testing.models import IterateModifier, LoadedTestDef, TestStatus
from tests.unit.factories import make_definition


def make_item(fn=None, *, modifiers=None) -> LoadedTestDef:
    return make_definition(
        "test_sample",
        fn=fn or (lambda: None),
        module_path="test_sample.py",
        modifiers=modifiers or [],
    )


@pytest.mark.asyncio
async def test_single_test_executes_without_runner():
    called: list[str] = []

    def test_body():
        called.append("called")

    definition = make_item(test_body)
    test = SingleTest(
        definition=definition,
        params={},
        node_key=definition.spec.full_name,
    )

    execution = await test.execute(ResourceResolver(registry))

    assert execution.result.status == TestStatus.PASSED
    assert called == ["called"]


def test_single_test_rejects_modifiers():
    definition = make_item(modifiers=[IterateModifier(count=2, min_passes=2)])
    with pytest.raises(ValueError, match="SingleTest should not have modifiers"):
        SingleTest(
            definition=definition,
            params={},
            node_key=definition.spec.full_name,
        )
