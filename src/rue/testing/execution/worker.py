"""Worker entrypoint and payloads for subprocess test execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from rue.config import Config
from rue.context.runtime import (
    CURRENT_RUN_ID,
    CURRENT_TEST,
    CURRENT_TEST_TRACER,
    TestContext,
    bind,
)
from rue.experiments.models import ExperimentVariant
from rue.experiments.registry import registry as default_experiment_registry
from rue.resources import ResourceResolver
from rue.resources.models import ResolverSyncSnapshot
from rue.resources.registry import registry as default_resource_registry
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
    snapshot: ResolverSyncSnapshot
    config: Config
    run_id: UUID
    execution_id: UUID
    experiment_variant: ExperimentVariant | None = None
    experiment_setup_chain: tuple[SetupFileRef, ...] = ()


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
        shadow_mode=True,
        sync_actor_id=payload.snapshot.sync_actor_id,
    )
    try:
        with bind(CURRENT_RUN_ID, payload.run_id):
            if payload.experiment_variant is not None:
                for ref in payload.experiment_setup_chain:
                    loader.prepare_setup(ref.path)
            for ref in payload.setup_chain:
                loader.prepare_setup(ref.path)

            if payload.experiment_variant is not None:
                await payload.experiment_variant.apply(
                    default_experiment_registry.all(),
                    resolver=resolver,
                    run_id=payload.run_id,
                )
            definition = loader.load_definition(
                payload.spec,
                setup_chain=payload.setup_chain,
            )
            test_ctx = TestContext(
                item=definition,
                execution_id=payload.execution_id,
                run_id=payload.run_id,
            )
            with bind(CURRENT_TEST, test_ctx):
                await resolver.hydrate_sync_snapshot(payload.snapshot)

        tracer = TestTracer.build(
            config=payload.config,
            run_id=payload.run_id,
        )
        with (
            bind(CURRENT_TEST, test_ctx),
            bind(CURRENT_RUN_ID, payload.run_id),
            bind(CURRENT_TEST_TRACER, tracer),
        ):
            tracer.start(definition, execution_id=payload.execution_id)
            duration_ms, imperative_outcome, error, assertion_results = (
                await definition.run_loaded_test(
                    resolver=resolver,
                    params=payload.params,
                    execution_id=payload.execution_id,
                    run_sync_in_thread=False,
                    run_id=payload.run_id,
                )
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
        sync_update = resolver.sync_update_since(
            payload.snapshot.base_state,
            list(payload.snapshot.res_specs),
        )
    finally:
        await resolver.teardown()
    return RemoteExecutionResult(
        result=result,
        telemetry_artifacts=telemetry_artifacts,
        sync_update=sync_update,
    )
