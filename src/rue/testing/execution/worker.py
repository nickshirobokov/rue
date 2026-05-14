"""Worker entrypoint and payloads for subprocess test execution."""

from __future__ import annotations

import asyncio

from rue.context.runtime import (
    CURRENT_TEST_TRACER,
    ModuleContext,
    TestContext,
    bind,
)
from rue.context.scopes import CurrentProcessKind
from rue.experiments.registry import registry as default_experiment_registry
from rue.resources import DependencyResolver
from rue.resources.registry import registry as default_resource_registry
from rue.testing.discovery.loader import TestLoader
from rue.testing.execution.test.models import (
    RemoteTestExecutionPayload,
    RemoteTestExecutionResult,
    TestResult,
)
from rue.testing.tracing import TestTracer


def execute_remote_test(
    payload: RemoteTestExecutionPayload,
) -> RemoteTestExecutionResult:
    """Synchronous entrypoint submitted to a ProcessPoolExecutor worker."""
    return asyncio.run(_execute_remote_test(payload))


async def _execute_remote_test(
    payload: RemoteTestExecutionPayload,
) -> RemoteTestExecutionResult:
    payload.context.process = CurrentProcessKind.TEST_SUBPROCESS
    with payload.context:
        loader = TestLoader(payload.suite_root)
        resolver = DependencyResolver(default_resource_registry)
        if payload.context.experiment_variant is not None:
            for ref in payload.context.experiment_setup_chain:
                loader.prepare_setup(ref.path)
        for ref in payload.setup_chain:
            loader.prepare_setup(ref.path)

        if payload.context.experiment_variant is not None:
            await payload.context.experiment_variant.apply(
                default_experiment_registry.all(),
                resolver=resolver,
            )
        definition = loader.load_definition(
            payload.spec,
            setup_chain=payload.setup_chain,
        )
        test_ctx = TestContext(test_execution_id=payload.test_execution_id)

    tracer = TestTracer.build(
        config=payload.context.config,
        suite_execution_id=payload.context.suite_execution_id,
    )
    with (
        payload.context,
        ModuleContext(payload.spec.locator.module_path),
        test_ctx,
        bind(CURRENT_TEST_TRACER, tracer),
    ):
        resource_update = None
        try:
            await resolver.update_from_snapshot(
                payload.resources,
                consumer_spec=definition.spec,
            )
            tracer.start(
                definition,
                test_execution_id=payload.test_execution_id,
            )
            (
                duration_ms,
                imperative_outcome,
                error,
                assertion_results,
            ) = await definition.execute_loaded_test(
                params=payload.params,
                resolver=resolver,
                execute_sync_in_thread=False,
            )
            result = TestResult.build(
                definition=definition,
                imperative_outcome=imperative_outcome,
                duration_ms=duration_ms,
                error=error,
                assertion_results=assertion_results,
            )
            tracer.record_result(result)
            telemetry_artifacts = tracer.finish()
            resource_update = await resolver.sync_snapshot(
                payload.resources,
            )
        finally:
            if resource_update is None:
                await resolver.teardown()
    return RemoteTestExecutionResult(
        result=result,
        telemetry_artifacts=telemetry_artifacts,
        resources=resource_update,
    )
