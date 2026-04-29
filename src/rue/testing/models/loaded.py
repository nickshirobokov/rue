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
    bind,
)
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

    ``suite_root`` and ``setup_chain`` capture the import context used to
    materialize this callable so expanded leaves still describe the original
    suite/session they came from.
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    spec: TestSpec
    fn: Callable[..., Any]
    suite_root: Path = field(default_factory=Path)
    setup_chain: tuple[SetupFileRef, ...] = field(default_factory=tuple)

    async def call_test_fn(
        self,
        kwargs: dict[str, Any],
        *,
        run_sync_in_thread: bool,
    ) -> None:
        """Call the loaded test function with resolved resource kwargs."""
        instance = None

        if self.spec.locator.class_name:
            cls = self.fn.__globals__.get(self.spec.locator.class_name)
            if cls is None:
                raise RuntimeError(
                    f"Test class '{self.spec.locator.class_name}' not found "
                    f"for test '{self.spec.locator.function_name}'"
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
        params: dict[str, Any],
        resolver: ResourceResolver,
        execution_id: UUID,
        run_sync_in_thread: bool,
        is_stopped: Callable[[], bool] | None = None,
    ) -> tuple[
        float,
        TestStatus | None,
        BaseException | None,
        list[AssertionResult],
    ]:
        """Resolve resources, run this test, and return execution metadata."""
        assertion_results: list[AssertionResult] = []
        error: BaseException | None = None
        imperative_outcome: TestStatus | None = None

        start = time.perf_counter()
        with bind(CURRENT_ASSERTION_RESULTS, assertion_results):
            try:
                kwargs = await resolver.resolve_test_deps(
                    execution_id,
                    params,
                    consumer_spec=self.spec,
                )
                if is_stopped is not None and is_stopped():
                    imperative_outcome = TestStatus.SKIPPED
                    error = Exception("Run stopped early")
                else:
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
            except Exception as raised:
                error = raised

        return (
            (time.perf_counter() - start) * 1000,
            imperative_outcome,
            error,
            assertion_results,
        )
