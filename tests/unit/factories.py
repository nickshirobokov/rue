"""Shared test factories for unit tests."""

from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.config import Config
from rue.context.runtime import CURRENT_RUN_CONTEXT, RunContext
from rue.context.scopes import CURRENT_SCOPE_CONTEXT, ScopeContext
from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.execution.base import ExecutionBackend
from rue.testing.models import BackendModifier, LoadedTestDef
from rue.testing.models.modifiers import Modifier
from rue.testing.models.spec import Locator, SetupFileRef, TestSpec


_COLLECTION_INDEX = count()


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
    backend: ExecutionBackend = ExecutionBackend.ASYNCIO,
    suffix: str | None = None,
    case_id: UUID | None = None,
    suite_root: str | Path | None = None,
    setup_chain: tuple[SetupFileRef, ...] = (),
    collection_index: int | None = None,
) -> LoadedTestDef:
    """Build a LoadedTestDef without needing a real module."""
    module_path = Path(module_path)
    all_modifiers = list(modifiers)
    if backend is not ExecutionBackend.ASYNCIO:
        all_modifiers.insert(0, BackendModifier(backend=backend))
    spec = TestSpec(
        locator=Locator(
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
        suffix=suffix,
        case_id=case_id,
        collection_index=(
            next(_COLLECTION_INDEX)
            if collection_index is None
            else collection_index
        ),
    )
    return LoadedTestDef(
        spec=spec,
        fn=fn or (lambda: None),
        suite_root=Path(suite_root)
        if suite_root is not None
        else module_path.parent,
        setup_chain=setup_chain,
    )


def materialize_tests(
    path: str | Path,
) -> list[LoadedTestDef]:
    collection = TestSpecCollector((), (), None).build_spec_collection((path,))
    return TestLoader(collection.suite_root).load_from_collection(collection)


def make_run_context(
    config: Config | None = None,
    *,
    run_id: UUID | None = None,
    **config_kwargs: Any,
) -> RunContext:
    if config is None:
        config = Config.model_construct(**config_kwargs)
    context = (
        RunContext(config=config)
        if run_id is None
        else RunContext(config=config, run_id=run_id)
    )
    CURRENT_RUN_CONTEXT.set(context)
    CURRENT_SCOPE_CONTEXT.set(ScopeContext.for_run(context.run_id))
    return context
