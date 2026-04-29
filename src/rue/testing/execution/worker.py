"""Worker entrypoint and payloads for subprocess test execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.context.runtime import (
    CURRENT_TEST_TRACER,
    RunContext,
    TestContext,
    bind,
)
from rue.experiments.registry import registry as default_experiment_registry
from rue.resources import ResourceResolver
from rue.resources.models import ResourceTransferSnapshot
from rue.resources.registry import registry as default_resource_registry
from rue.resources.state import ResourceStore
from rue.telemetry.base import TelemetryArtifact
from rue.testing.discovery.loader import TestLoader
from rue.testing.models import TestResult
from rue.testing.models.spec import SetupFileRef, TestSpec
from rue.testing.tracing import TestTracer


@dataclass(frozen=True, slots=True)
class ExecutorPayload:
    """Minimal, fully-serializable payload for remote test execution."""

    spec: TestSpec
    suite_root: Path
    setup_chain: tuple[SetupFileRef, ...]
    params: dict[str, Any]
    snapshot: ResourceTransferSnapshot
    context: RunContext
    execution_id: UUID


@dataclass(frozen=True, slots=True)
class RemoteExecutionResult:
    """Serializable remote execution outcome."""

    result: TestResult
    telemetry_artifacts: tuple[TelemetryArtifact, ...]
    sync_update: bytes


def run_remote_test(payload: ExecutorPayload) -> RemoteExecutionResult:
    """Synchronous entrypoint submitted to a ProcessPoolExecutor worker."""
    return asyncio.run(_run_remote_test(payload))


async def _run_remote_test(payload: ExecutorPayload) -> RemoteExecutionResult:
    loader = TestLoader(payload.suite_root)
    resolver = ResourceResolver(
        default_resource_registry,
        resources=ResourceStore.shadow(
            sync_actor_id=payload.snapshot.actor_id,
        ),
    )
    with payload.context:
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
        test_ctx = TestContext(
            item=definition,
            execution_id=payload.execution_id,
        )

    tracer = TestTracer.build(
        config=payload.context.config,
        run_id=payload.context.run_id,
    )
    with (
        payload.context,
        test_ctx,
        bind(CURRENT_TEST_TRACER, tracer),
    ):
        try:
            await resolver.transfer.hydrate(
                payload.snapshot,
                consumer_spec=definition.spec,
            )
            tracer.start(definition, execution_id=payload.execution_id)
            (
                duration_ms,
                imperative_outcome,
                error,
                assertion_results,
            ) = await definition.run_loaded_test(
                params=payload.params,
                resolver=resolver,
                run_sync_in_thread=False,
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
            sync_update = resolver.transfer.update_since(
                payload.snapshot.base_state,
                list(payload.snapshot.resource_specs),
            )
        finally:
            await resolver.teardown()
    return RemoteExecutionResult(
        result=result,
        telemetry_artifacts=telemetry_artifacts,
        sync_update=sync_update,
    )
