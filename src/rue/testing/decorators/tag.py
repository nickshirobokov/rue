"""Tag decorators for Rue tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TagData:
    """Tag metadata attached to callables or classes."""

    tags: set[str] = field(default_factory=set)
    skip_reason: str | None = None
    xfail_reason: str | None = None
    xfail_strict: bool = False


def get_tag_data(target: Any) -> TagData:
    """Return a copy of tag metadata for the target."""
    data: TagData | None = getattr(target, "__rue_tag_data__", None)
    if data is None:
        return TagData()
    return TagData(
        tags=set(data.tags),
        skip_reason=data.skip_reason,
        xfail_reason=data.xfail_reason,
        xfail_strict=data.xfail_strict,
    )


def merge_tag_data(*datas: TagData | None) -> TagData:
    """Merge tag metadata, later entries overriding earlier ones."""
    merged = TagData()
    for data in datas:
        if not data:
            continue
        merged.tags.update(data.tags)
        if data.skip_reason is not None:
            merged.skip_reason = data.skip_reason
        if data.xfail_reason is not None:
            merged.xfail_reason = data.xfail_reason
            merged.xfail_strict = data.xfail_strict
    return merged


class TagDecorator:
    """Primary entry-point for tagging tests."""

    def __call__(self, *names: str) -> Callable[[Any], Any]:
        def decorator(target: Any) -> Any:
            data = getattr(target, "__rue_tag_data__", None)
            target.__rue_tag_data__ = data = TagData() if data is None else data
            for name in names:
                if not name:
                    continue
                data.tags.add(str(name))
            target.__rue_test__ = True
            return target

        return decorator

    def skip(self, *, reason: str | None = None) -> Callable[[Any], Any]:
        def decorator(target: Any) -> Any:
            data = getattr(target, "__rue_tag_data__", None)
            target.__rue_tag_data__ = data = TagData() if data is None else data
            data.skip_reason = reason or "skipped via tag"
            data.tags.add("skip")
            target.__rue_test__ = True
            return target

        return decorator

    def xfail(
        self,
        *,
        reason: str | None = None,
        strict: bool = False,
    ) -> Callable[[Any], Any]:
        def decorator(target: Any) -> Any:
            data = getattr(target, "__rue_tag_data__", None)
            target.__rue_tag_data__ = data = TagData() if data is None else data
            data.xfail_reason = reason or "expected failure"
            data.xfail_strict = strict
            data.tags.add("xfail")
            target.__rue_test__ = True
            return target

        return decorator


tag = TagDecorator()


__all__ = ["TagData", "TagDecorator", "get_tag_data", "merge_tag_data", "tag"]
