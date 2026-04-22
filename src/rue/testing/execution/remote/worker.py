"""Worker-side entrypoint for remote test execution."""

from __future__ import annotations

import asyncio
import time

from rue.assertions.base import AssertionResult
from rue.context.collectors import CURRENT_ASSERTION_RESULTS
from rue.context.runtime import (
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)

from rue.resources import ResourceResolver
from rue.resources.registry import registry as default_resource_registry
from rue.testing.discovery.loader import TestLoader
from rue.testing.execution.remote.models import (
    ExecutorPayload,
    RemoteExecutionResult,
)
from rue.testing.models import TestResult, TestStatus
from rue.testing.outcomes import FailTest, SkipTest, XFailTest
from rue.testing.tracing import build_test_tracer


def run_remote_test(payload: ExecutorPayload) -> RemoteExecutionResult:
    """Synchronous entrypoint submitted to a ProcessPoolExecutor worker."""
    return asyncio.run(_run_remote_test(payload))


async def _run_remote_test(payload: ExecutorPayload) -> RemoteExecutionResult:
    loader = TestLoader(payload.suite_root)
    for ref in payload.setup_chain:
        loader.prepare_setup(ref.path)

    definition = loader.load_definition(
        payload.spec,
        setup_chain=payload.setup_chain,
    )

    resolver = await ResourceResolver.hydrate_from_sync_snapshot(
        payload.snapshot,
        default_resource_registry,
    )

    tracer = build_test_tracer(
        config=payload.config,
        run_id=payload.run_id,
    )
    assertion_results: list[AssertionResult] = []
    error: BaseException | None = None
    imperative_outcome: TestStatus | None = None
    ctx = TestContext(item=definition, execution_id=payload.execution_id)

    with bind(CURRENT_TEST_TRACER, tracer):
        tracer.start(definition, execution_id=payload.execution_id)
        with (
            bind(CURRENT_TEST, ctx),
            bind(CURRENT_ASSERTION_RESULTS, assertion_results),
        ):
            try:
                start = time.perf_counter()
                unresolved_params = tuple(
                    param
                    for param in definition.spec.params
                    if param not in payload.params
                )
                kwargs = await resolver.partially_resolve(
                    unresolved_params,
                    payload.params,
                )
                await definition.call_test_fn(
                    kwargs=kwargs,
                    run_sync_in_thread=False,
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

        duration_ms = (time.perf_counter() - start) * 1000
        result = TestResult.build(
            definition=definition,
            imperative_outcome=imperative_outcome,
            duration_ms=duration_ms,
            error=error,
            assertion_results=assertion_results,
        )
        tracer.record_result(result)
        telemetry_artifacts = tracer.finish()

    sync_update = resolver.sync_update_since(
        payload.snapshot.base_state,
        list(payload.snapshot.res_specs),
    )

    return RemoteExecutionResult(
        result=result,
        telemetry_artifacts=telemetry_artifacts,
        sync_update=sync_update,
    )
