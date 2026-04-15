"""Tests for imperative outcomes (skip, fail, xfail)."""

from pathlib import Path

import pytest

from rue.testing import TestStatus, fail, skip, xfail
from rue.testing.models import LoadedTestDef
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.runner import Runner
from tests.unit.factories import make_definition


def make_item(
    fn, name: str | None = None, is_async: bool = False
) -> LoadedTestDef:
    return make_definition(name or fn.__name__, fn=fn, is_async=is_async)


@pytest.mark.parametrize(
    ("outcome_fn", "status", "count_attr", "error_type", "reason"),
    [
        (skip, TestStatus.SKIPPED, "skipped", SkipTest, "missing dependency"),
        (fail, TestStatus.FAILED, "failed", FailTest, "explicit failure"),
        (xfail, TestStatus.XFAILED, "xfailed", XFailTest, "known bug"),
    ],
)
@pytest.mark.asyncio
async def test_imperative_outcome_sets_status_and_reason(
    null_reporter,
    outcome_fn,
    status,
    count_attr: str,
    error_type,
    reason: str,
):
    def outcome_test():
        outcome_fn(reason)

    result = await Runner(reporters=[null_reporter]).run(
        items=[make_item(outcome_test)]
    )
    execution = result.result.executions[0]

    assert getattr(result.result, count_attr) == 1
    assert execution.result.status == status
    assert isinstance(execution.result.error, error_type)
    assert reason in str(execution.result.error)


@pytest.mark.parametrize(
    ("outcome_fn", "count_attr", "error_type"),
    [
        (skip, "skipped", SkipTest),
        (fail, "failed", FailTest),
        (xfail, "xfailed", XFailTest),
    ],
)
@pytest.mark.asyncio
async def test_imperative_outcome_without_reason_uses_expected_error_type(
    null_reporter,
    outcome_fn,
    count_attr: str,
    error_type,
):
    def outcome_test():
        outcome_fn()

    result = await Runner(reporters=[null_reporter]).run(
        items=[make_item(outcome_test)]
    )

    assert getattr(result.result, count_attr) == 1
    assert isinstance(result.result.executions[0].result.error, error_type)


@pytest.mark.parametrize("outcome_fn", [skip, fail, xfail])
@pytest.mark.asyncio
async def test_imperative_outcome_stops_execution(
    null_reporter,
    outcome_fn,
):
    executed = []

    def outcome_test():
        executed.append("before")
        outcome_fn("stopping")
        executed.append("after")

    await Runner(reporters=[null_reporter]).run(items=[make_item(outcome_test)])

    assert executed == ["before"]
