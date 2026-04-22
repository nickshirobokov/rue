"""Shared test factories for unit tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.execution.types import ExecutionBackend
from rue.testing.models import BackendModifier, LoadedTestDef
from rue.testing.models.modifiers import Modifier
from rue.testing.models.spec import SetupFileRef, TestLocator, TestSpec


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
    backend: ExecutionBackend = ExecutionBackend.ASYNCIO,
    fail_fast: bool = False,
    suffix: str | None = None,
    case_id: UUID | None = None,
    suite_root: str | Path | None = None,
    setup_chain: tuple[SetupFileRef, ...] = (),
) -> LoadedTestDef:
    """Build a LoadedTestDef for use in unit tests without needing a real module."""
    module_path = Path(module_path)
    all_modifiers = list(modifiers)
    if backend is not ExecutionBackend.ASYNCIO:
        all_modifiers.insert(0, BackendModifier(backend=backend))
    spec = TestSpec(
        locator=TestLocator(
            module_path=module_path,
            function_name=name,
            class_name=class_name,
        ),
        is_async=is_async,
        params=tuple(params),
        modifiers=tuple(all_modifiers),
        tags=frozenset(tags),
        skip_reason=skip_reason,
        xfail_reason=xfail_reason,
        xfail_strict=xfail_strict,
        definition_error=definition_error,
        suffix=suffix,
        case_id=case_id,
    )
    return LoadedTestDef(
        spec=spec,
        fn=fn or (lambda: None),
        suite_root=Path(suite_root)
        if suite_root is not None
        else module_path.parent,
        setup_chain=setup_chain,
        fail_fast=fail_fast,
    )


def materialize_tests(
    path: str | Path,
) -> list[LoadedTestDef]:
    collection = TestSpecCollector((), (), None).build_spec_collection((path,))
    return TestLoader(collection.suite_root).load_from_collection(collection)
