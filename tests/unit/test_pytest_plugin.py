from __future__ import annotations

from typing import Any

from rue import pytest_plugin


class _FakeItem:
    __slots__ = ("cls", "obj")

    def __init__(self, obj: Any, cls: type | None = None) -> None:
        self.obj = obj
        self.cls = cls


def _fn_rue() -> None:
    return None


_fn_rue.__rue_test__ = True  # type: ignore[attr-defined]


def _fn_plain() -> None:
    return None


class _RueCls:
    __rue_test__ = True


def test_pytest_collection_modifyitems_drops_rue_callables():
    items: list[Any] = [
        _FakeItem(_fn_plain),
        _FakeItem(_fn_rue),
    ]
    pytest_plugin.pytest_collection_modifyitems(None, None, items)
    assert len(items) == 1
    assert items[0].obj is _fn_plain


def test_pytest_collection_modifyitems_drops_methods_on_rue_class():
    def method() -> None:
        return None

    items = [_FakeItem(method, cls=_RueCls)]
    pytest_plugin.pytest_collection_modifyitems(None, None, items)
    assert items == []
