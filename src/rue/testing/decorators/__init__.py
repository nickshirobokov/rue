"""Test decorators."""

from dataclasses import dataclass

from rue.testing.decorators.iterate import iterate
from rue.testing.decorators.tag import (
    TagData,
    get_tag_data,
    merge_tag_data,
    tag,
)


@dataclass(frozen=True)
class TestDecoratorNamespace: #temp object until we figure out what raw test decorator should do 
    iterate: object
    tag: object


test = TestDecoratorNamespace(iterate=iterate, tag=tag)

__all__ = [
    "TagData",
    "TestDecoratorNamespace",
    "get_tag_data",
    "iterate",
    "merge_tag_data",
    "tag",
    "test",
]
