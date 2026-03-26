from pathlib import Path

import pytest

from rue.resources import ResourceResolver
from rue.testing.execution.result_builder import ResultBuilder
from rue.testing.execution.single import SingleTest
from rue.testing.models import RepeatModifier, TestItem, TestStatus


def make_item(fn=None, *, modifiers=None) -> TestItem:
    return TestItem(
        name="test_sample",
        fn=fn or (lambda: None),
        module_path=Path("test_sample.py"),
        is_async=False,
        modifiers=modifiers or [],
    )


@pytest.mark.asyncio
async def test_single_test_executes_without_runner():
    called: list[str] = []

    def test_body():
        called.append("called")

    test = SingleTest(
        definition=make_item(test_body),
        params={},
        result_builder=ResultBuilder(),
    )

    execution = await test.execute(ResourceResolver())

    assert execution.result.status == TestStatus.PASSED
    assert called == ["called"]


def test_single_test_rejects_modifiers():
    with pytest.raises(
        ValueError, match="SingleTest should not have modifiers"
    ):
        SingleTest(
            definition=make_item(
                modifiers=[RepeatModifier(count=2, min_passes=2)]
            ),
            params={},
            result_builder=ResultBuilder(),
        )
