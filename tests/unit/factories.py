"""Shared test factories for unit tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.models import LoadedTestDef
from rue.testing.models.modifiers import Modifier
from rue.testing.models.spec import TestLocator, TestSpec


def make_definition(
    name: str = "test_fn",
    *,
    fn: Callable[..., Any] | None = None,
    module_path: str | Path = "test_module.py",
    is_async: bool = False,
    params: list[str] | tuple[str, ...] = (),
    class_name: str | None = None,
    modifiers: list[Modifier] | tuple[Modifier, ...] = (),
    tags: set[str] | frozenset[str] = frozenset(),
    skip_reason: str | None = None,
    xfail_reason: str | None = None,
    xfail_strict: bool = False,
    definition_error: str | None = None,
    inline: bool = False,
    fail_fast: bool = False,
    suffix: str | None = None,
    case_id: UUID | None = None,
) -> LoadedTestDef:
    """Build a LoadedTestDef for use in unit tests without needing a real module."""
    spec = TestSpec(
        locator=TestLocator(
            module_path=Path(module_path),
            function_name=name,
            class_name=class_name,
        ),
        is_async=is_async,
        params=tuple(params),
        modifiers=tuple(modifiers),
        tags=frozenset(tags),
        skip_reason=skip_reason,
        xfail_reason=xfail_reason,
        xfail_strict=xfail_strict,
        definition_error=definition_error,
        inline=inline,
        suffix=suffix,
        case_id=case_id,
    )
    return LoadedTestDef(spec=spec, fn=fn or (lambda: None), fail_fast=fail_fast)


def materialize_tests(
    path: str | Path,
) -> list[LoadedTestDef]:
    collection = TestSpecCollector((), (), None).build_spec_collection((path,))
    return TestLoader(collection.suite_root).load_from_collection(collection)
