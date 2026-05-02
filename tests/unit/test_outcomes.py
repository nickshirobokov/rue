"""Tests for imperative outcomes (skip, fail, xfail)."""

import pytest

from rue.resources import DependencyResolver, registry
from rue.testing import TestStatus, fail, skip, xfail
from rue.testing.models import LoadedTestDef
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.runner import Runner
from tests.helpers import make_definition, make_run_context


def make_item(
    fn, name: str | None = None, is_async: bool = False
) -> LoadedTestDef:
    return make_definition(name or fn.__name__, fn=fn, is_async=is_async)


def make_runner() -> Runner:
    make_run_context()
    return Runner()


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
    outcome_fn,
    status,
    count_attr: str,
    error_type,
    reason: str,
):
    def outcome_test():
        outcome_fn(reason)

    result = await make_runner().run(
        items=[make_item(outcome_test)],
        resolver=DependencyResolver(registry),
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
    outcome_fn,
    count_attr: str,
    error_type,
):
    def outcome_test():
        outcome_fn()

    result = await make_runner().run(
        items=[make_item(outcome_test)],
        resolver=DependencyResolver(registry),
    )

    assert getattr(result.result, count_attr) == 1
    assert isinstance(result.result.executions[0].result.error, error_type)


@pytest.mark.parametrize("outcome_fn", [skip, fail, xfail])
@pytest.mark.asyncio
async def test_imperative_outcome_stops_execution(
    outcome_fn,
):
    executed = []

    def outcome_test():
        executed.append("before")
        outcome_fn("stopping")
        executed.append("after")

    await make_runner().run(
        items=[make_item(outcome_test)],
        resolver=DependencyResolver(registry),
    )

    assert executed == ["before"]
