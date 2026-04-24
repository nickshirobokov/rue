"""Loaded test definition — process-bound pair of spec + live callable."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.assertions.base import AssertionResult
from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import (
    CURRENT_RESOURCE_RESOLVER,
    CURRENT_TEST,
    TestContext,
    bind,
)
from rue.patching.runtime import PatchContext, patch_manager
from rue.resources import ResourceResolver
from rue.testing.models.result import TestStatus
from rue.testing.models.spec import SetupFileRef, TestSpec
from rue.testing.outcomes import FailTest, SkipTest, XFailTest


@dataclass
class LoadedTestDef:
    """A discovered test function ready for execution in the current process.

    Pairs a serializable :class:`TestSpec` with the live callable resolved
    by the loader.  The ``spec`` is the cross-process-safe record; ``fn`` is
    the process-local binding.

    ``fail_fast`` is the one runtime-mutable field: it is not part of the
    spec because it is set by the :class:`Runner` after collection, not by
    user decorators.

    ``suite_root`` and ``setup_chain`` capture the import context used to
    materialize this callable so expanded leaves still describe the original
    suite/session they came from.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    spec: TestSpec
    fn: Callable[..., Any]
    suite_root: Path = field(default_factory=Path)
    setup_chain: tuple[SetupFileRef, ...] = field(default_factory=tuple)
    fail_fast: bool = field(default=False)
    load_error: str | None = field(default=None)

    @classmethod
    def from_load_error(
        cls,
        spec: TestSpec,
        *,
        suite_root: Path,
        setup_chain: tuple[SetupFileRef, ...],
        load_error: str,
    ) -> "LoadedTestDef":
        return cls(
            spec=spec,
            fn=lambda: None,
            suite_root=suite_root,
            setup_chain=setup_chain,
            load_error=load_error,
        )

    async def call_test_fn(
        self,
        kwargs: dict[str, Any],
        *,
        run_sync_in_thread: bool,
    ) -> None:
        instance = None

        if self.spec.class_name:
            cls = self.fn.__globals__.get(self.spec.class_name)
            if cls is None:
                raise RuntimeError(
                    f"Test class '{self.spec.class_name}' not found "
                    f"for test '{self.spec.name}'"
                )
            instance = cls()

        call = (
            partial(self.fn, instance, **kwargs)
            if instance
            else partial(self.fn, **kwargs)
        )

        if self.spec.is_async:
            await call()
        elif run_sync_in_thread:
            await asyncio.to_thread(call)
        else:
            call()

    async def run_loaded_test(
        self,
        *,
        resolver: ResourceResolver,
        params: dict[str, Any],
        execution_id: UUID,
        run_sync_in_thread: bool,
        run_id: UUID | None = None,
        is_stopped: Callable[[], bool] | None = None,
    ) -> tuple[
        float,
        TestStatus | None,
        BaseException | None,
        list[AssertionResult],
    ]:
        assertion_results: list[AssertionResult] = []
        error: BaseException | None = None
        imperative_outcome: TestStatus | None = None
        ctx = TestContext(item=self, execution_id=execution_id, run_id=run_id)

        start = time.perf_counter()
        with (
            bind(CURRENT_TEST, ctx),
            bind(CURRENT_ASSERTION_RESULTS, assertion_results),
            bind(CURRENT_RESOURCE_RESOLVER, resolver),
        ):
            try:
                autouse_names = await resolver.resolve_autouse(
                    self.spec.module_path
                )
                unresolved_params = tuple(
                    param for param in self.spec.params if param not in params
                )
                kwargs = await resolver.partially_resolve(
                    unresolved_params,
                    params,
                )
                if is_stopped is not None and is_stopped():
                    imperative_outcome = TestStatus.SKIPPED
                    error = Exception("Run stopped early")
                else:
                    resource_names = (*autouse_names, *unresolved_params)
                    resources = (
                        resolver.collect_dependency_closure(
                            resource_names,
                            request_path=self.spec.module_path,
                        )
                        if resource_names
                        else ()
                    )
                    with patch_manager.bind_context(
                        PatchContext(
                            execution_id=execution_id,
                            run_id=run_id,
                            module_path=self.spec.module_path.resolve(),
                            resources=frozenset(resources),
                        )
                    ):
                        await self.call_test_fn(
                            kwargs=kwargs,
                            run_sync_in_thread=run_sync_in_thread,
                        )
            except SkipTest as raised:
                imperative_outcome = TestStatus.SKIPPED
                error = raised
            except FailTest as raised:
                imperative_outcome = TestStatus.FAILED
                error = raised
            except XFailTest as raised:
                imperative_outcome = TestStatus.XFAILED
                error = raised
            except Exception as raised:  # noqa: BLE001
                error = raised

        return (
            (time.perf_counter() - start) * 1000,
            imperative_outcome,
            error,
            assertion_results,
        )
