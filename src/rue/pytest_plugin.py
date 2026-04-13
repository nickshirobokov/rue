"""Pytest plugin: drop Rue tests from default pytest collection."""

from __future__ import annotations


def pytest_collection_modifyitems(
    session: object, config: object, items: list[object]
) -> None:
    """Drop Rue-marked tests so pytest does not collect them."""
    del session, config
    items[:] = [item for item in items if not _is_rue_test(item)]


def _is_rue_test(item: object) -> bool:
    obj = getattr(item, "obj", None)
    if obj is not None and getattr(obj, "__rue_test__", False):
        return True
    cls = getattr(item, "cls", None)
    return bool(cls and getattr(cls, "__rue_test__", False))
