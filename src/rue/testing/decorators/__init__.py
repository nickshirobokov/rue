"""Test decorators."""

from collections.abc import Callable
from typing import Any

from rue.testing.decorators.backend import backend
from rue.testing.decorators.iterate import iterate
from rue.testing.decorators.tag import (
    TagData,
    get_tag_data,
    merge_tag_data,
    tag,
)


def test(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn.__rue_test__ = True  # type: ignore[attr-defined]
    return fn


__all__ = [
    "TagData",
    "backend",
    "get_tag_data",
    "iterate",
    "merge_tag_data",
    "tag",
    "test",
]
