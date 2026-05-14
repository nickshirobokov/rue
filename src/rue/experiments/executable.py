"""Executable experiment suites."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from os import devnull
from typing import Any

import cloudpickle  # type: ignore[import-untyped]

from rue.config import Config
from rue.context.runtime import SuiteContext
from rue.context.scopes import CurrentProcessKind
from rue.events import (
    QueueForwarder,
    SessionEventsReceiver,
    SuiteEventsProcessor,
)
from rue.events.receiver import SuiteEventsReceiver
from rue.experiments.models import (
    ExperimentSpec,
    ExperimentVariant,
    ExperimentVariantResult,
)
from rue.experiments.registry import registry as default_experiment_registry
from rue.resources import DependencyResolver
from rue.resources.registry import registry as default_resource_registry
from rue.storage import TursoSuiteRecorder, TursoSuiteStore
from rue.telemetry.otel import OtelReporter
from rue.testing.discovery import TestLoader
from rue.testing.execution.suite.executable import ExecutableSuite
from rue.testing.models import SuiteSpec


DRAIN_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class ExecutableExperiment:
    """Executes experiment variants as isolated child suites."""

    config: Config

    def collect(
        self, suitespec: SuiteSpec
    ) -> tuple[ExperimentSpec, ...]:
        """Load setup files and return registered experiments."""
        default_resource_registry.reset()
        default_experiment_registry.reset()
        loader = TestLoader(suitespec.suite_root)
        for setup_ref in suitespec.all_setup_files:
            loader.prepare_setup(setup_ref.path, reload=True)
        return default_experiment_registry.all()

    async def execute(
        self,
        suitespec: SuiteSpec,
        experiments: tuple[ExperimentSpec, ...],
        *,
        session: SessionEventsReceiver,
    ) -> tuple[ExperimentVariantResult, ...]:
        """Execute baseline plus every experiment value combination."""
        results: list[ExperimentVariantResult] = []
        variants = (
            (ExperimentVariant(index=0),)
            if not experiments
            else ExperimentVariant.build_all(experiments)
        )
        mp_context = mp.get_context("spawn")
        manager = mp_context.Manager()
        with ProcessPoolExecutor(
            # TODO: keep as 1 until Turso ships 0.6 with concurrent writes.
            max_workers=1,
            max_tasks_per_child=1,
            mp_context=mp_context,
        ) as pool:
            try:
                for variant in variants:
                    queue = manager.Queue()
                    future = pool.submit(
                        execute_experiment_variant,
                        cloudpickle.dumps(
                            (suitespec, variant, self.config),
                        ),
                        queue,
                    )
                    drain_task = asyncio.create_task(
                        session.drain_queue(queue)
                    )
                    try:
                        result = await asyncio.to_thread(future.result)
                    finally:
                        queue.put(None)
                        await asyncio.wait_for(
                            drain_task,
                            timeout=DRAIN_TIMEOUT_SECONDS,
                        )
                    results.append(result)
            finally:
                manager.shutdown()
        return tuple(results)


def execute_experiment_variant(
    payload: bytes,
    queue: Any,
) -> ExperimentVariantResult:
    """Process entrypoint for one experiment variant."""
    suitespec, variant, config = cloudpickle.loads(payload)
    return asyncio.run(
        _execute_experiment_variant(suitespec, variant, config, queue)
    )


async def _execute_experiment_variant(
    suitespec: SuiteSpec,
    variant: ExperimentVariant,
    config: Config,
    queue: Any,
) -> ExperimentVariantResult:
    default_resource_registry.reset()
    default_experiment_registry.reset()
    loader = TestLoader(suitespec.suite_root)
    for setup_ref in suitespec.all_setup_files:
        loader.prepare_setup(setup_ref.path)

    context = SuiteContext(
        config=config,
        process=CurrentProcessKind.EXPERIMENT_SUBPROCESS,
        experiment_variant=variant,
        experiment_setup_chain=suitespec.all_setup_files,
    )
    store = TursoSuiteStore(config.database_path)
    store.initialize()
    resolver = DependencyResolver(default_resource_registry)
    suite = None
    processors: list[SuiteEventsProcessor] = [TursoSuiteRecorder()]
    if config.otel:
        processors.append(OtelReporter())
    processors.append(QueueForwarder(queue))
    with ExitStack() as output_suppression:
        sink = output_suppression.enter_context(open(devnull, "w"))
        output_suppression.enter_context(redirect_stdout(sink))
        output_suppression.enter_context(redirect_stderr(sink))
        with context, SuiteEventsReceiver(processors):
            try:
                await variant.apply(
                    default_experiment_registry.all(),
                    resolver=resolver,
                )
                items = loader.load_tests(suitespec)
                suite = await ExecutableSuite(
                    items=items,
                    suite_execution_id=context.suite_execution_id,
                    resolver=resolver,
                ).execute()
            finally:
                if suite is None:
                    await resolver.teardown()
    if suite is None:
        raise ValueError("Suite was not created")
    return ExperimentVariantResult.build(variant=variant, suite=suite)


__all__ = [
    "ExecutableExperiment",
    "execute_experiment_variant",
]
