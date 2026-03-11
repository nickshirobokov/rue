"""Example rue tests demonstrating imperative outcomes (skip, fail, xfail)."""

import os

import rue


def test_skip_when_env_missing():
    """Skip test if required environment variable is not set."""
    if "API_KEY" not in os.environ:
        rue.skip("API_KEY not configured")

    assert os.environ["API_KEY"] is not None


def test_skip_unconditionally():
    """Skip a test unconditionally."""
    rue.skip("not implemented yet")


def test_fail_on_invalid_state():
    """Explicitly fail when detecting invalid state."""
    data = {"status": "error"}

    if data["status"] == "error":
        rue.fail("received error status from API")

    assert data["status"] == "ok"


def test_xfail_known_bug():
    """Mark test as expected failure for a known bug."""
    rue.xfail("issue #42: division by zero not handled")

    result = 1 / 0  # This will raise ZeroDivisionError
    assert result == 0


def test_conditional_xfail():
    """Conditionally mark as expected failure."""
    import sys

    if sys.version_info < (3, 12):
        rue.xfail("feature requires Python 3.12+")

    assert True


async def test_async_skip():
    """Skip works in async tests too."""
    rue.skip("async feature not ready")


class TestOutcomeTests:
    """Outcomes work in class methods."""

    def test_skip_in_class(self):
        rue.skip("class test skipped")

    def test_fail_in_class(self):
        rue.fail("class test failed")

    def test_xfail_in_class(self):
        rue.xfail("class test xfailed")
