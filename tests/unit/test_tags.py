import asyncio
from pathlib import Path

from rue.testing import Runner
from rue.testing.decorators.tags import get_tag_data, tag
from rue.testing.discovery import TestItem


def test_tag_decorator_records_metadata():
    @tag("slow", "llm")
    @tag.skip(reason="network down")
    @tag.xfail(reason="flaky", strict=True)
    def sample():
        pass

    data = get_tag_data(sample)
    assert data.tags == {"slow", "llm", "skip", "xfail"}
    assert data.skip_reason == "network down"
    assert data.xfail_reason == "flaky"
    assert data.xfail_strict is True


def test_runner_handles_skip_and_xfail(null_reporter):
    runner = Runner(reporters=[null_reporter])

    def test_skip():
        raise AssertionError("should not run")

    skip_item = TestItem(
        name="test_skip",
        fn=test_skip,
        module_path=Path("sample.py"),
        is_async=False,
        params=[],
        skip_reason="skip me",
        tags={"skip"},
    )

    def test_xfail():
        raise AssertionError("boom")

    xfail_item = TestItem(
        name="test_xfail",
        fn=test_xfail,
        module_path=Path("sample.py"),
        is_async=False,
        params=[],
        xfail_reason="known bug",
        tags={"xfail"},
    )

    run_result = asyncio.run(runner.run(items=[skip_item, xfail_item]))

    assert run_result.result.skipped == 1
    assert run_result.result.xfailed == 1
    assert run_result.result.passed == 0
