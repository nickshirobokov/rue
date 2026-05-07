"""Experiment runner."""

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
from rue.context.runtime import RunContext
from rue.events import QueueForwarder, RunEventsProcessor, SessionEventsReceiver
from rue.events.receiver import RunEventsReceiver
from rue.experiments.models import (
    ExperimentSpec,
    ExperimentVariant,
    ExperimentVariantResult,
)
from rue.experiments.registry import registry as default_experiment_registry
from rue.resources import DependencyResolver
from rue.resources.registry import registry as default_resource_registry
from rue.storage import TursoRunRecorder, TursoRunStore
from rue.telemetry.otel import OtelReporter
from rue.testing.discovery import TestLoader
from rue.testing.models.spec import TestSpecCollection
from rue.testing.runner import Runner


DRAIN_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class ExperimentRunner:
    """Runs experiment variants as isolated processes."""

    config: Config

    def collect(
        self, collection: TestSpecCollection
    ) -> tuple[ExperimentSpec, ...]:
        """Load setup files and return registered experiments."""
        default_resource_registry.reset()
        default_experiment_registry.reset()
        loader = TestLoader(collection.suite_root)
        for setup_ref in collection.all_setup_files:
            loader.prepare_setup(setup_ref.path, reload=True)
        return default_experiment_registry.all()

    async def run(
        self,
        collection: TestSpecCollection,
        experiments: tuple[ExperimentSpec, ...] | None = None,
        *,
        session: SessionEventsReceiver | None = None,
    ) -> tuple[ExperimentVariantResult, ...]:
        """Run baseline plus every experiment value combination."""
        experiment_specs = (
            self.collect(collection) if experiments is None else experiments
        )

        results: list[ExperimentVariantResult] = []
        variants = (
            (ExperimentVariant(index=0),)
            if not experiment_specs
            else ExperimentVariant.build_all(experiment_specs)
        )
        mp_context = mp.get_context("spawn")
        manager = mp_context.Manager() if session is not None else None
        with ProcessPoolExecutor(
            max_workers=1,
            max_tasks_per_child=1,
            mp_context=mp_context,
        ) as pool:
            try:
                for variant in variants:
                    queue = None if manager is None else manager.Queue()
                    future = pool.submit(
                        run_experiment_variant,
                        cloudpickle.dumps(
                            (collection, variant, self.config),
                        ),
                        queue,
                    )
                    drain_task = (
                        None
                        if session is None or queue is None
                        else asyncio.create_task(session.drain_queue(queue))
                    )
                    try:
                        result = await asyncio.to_thread(future.result)
                    finally:
                        if drain_task is not None:
                            queue.put(None)
                            await asyncio.wait_for(
                                drain_task,
                                timeout=DRAIN_TIMEOUT_SECONDS,
                            )
                    results.append(result)
            finally:
                if manager is not None:
                    manager.shutdown()
        return tuple(results)


def run_experiment_variant(
    payload: bytes,
    queue: Any | None = None,
) -> ExperimentVariantResult:
    """Process entrypoint for one experiment variant."""
    collection, variant, config = cloudpickle.loads(payload)
    return asyncio.run(
        _run_experiment_variant(
            collection,
            variant,
            config,
            queue,
        )
    )


async def _run_experiment_variant(
    collection: TestSpecCollection,
    variant: ExperimentVariant,
    config: Config,
    queue: Any | None = None,
) -> ExperimentVariantResult:
    default_resource_registry.reset()
    default_experiment_registry.reset()
    loader = TestLoader(collection.suite_root)
    for setup_ref in collection.all_setup_files:
        loader.prepare_setup(setup_ref.path)

    context = RunContext(
        config=config,
        experiment_variant=variant,
        experiment_setup_chain=collection.all_setup_files,
    )
    store = TursoRunStore(config.database_path)
    store.initialize()
    resolver = DependencyResolver(default_resource_registry)
    run = None
    processors: list[RunEventsProcessor] = [TursoRunRecorder()]
    if config.otel:
        processors.append(OtelReporter())
    if queue is not None:
        processors.append(QueueForwarder(queue))
    output_suppression = ExitStack()
    if queue is not None:
        sink = output_suppression.enter_context(open(devnull, "w"))
        output_suppression.enter_context(redirect_stdout(sink))
        output_suppression.enter_context(redirect_stderr(sink))
    with output_suppression, context, RunEventsReceiver(processors):
        try:
            await variant.apply(
                default_experiment_registry.all(),
                resolver=resolver,
            )
            items = loader.load_from_collection(collection)
            runner = Runner()
            run = await runner.run(items, resolver=resolver)
        finally:
            if run is None:
                await resolver.teardown()
    if run is None:
        raise ValueError("Run was not created")
    return ExperimentVariantResult.build(variant=variant, run=run)


__all__ = [
    "ExperimentRunner",
    "run_experiment_variant",
]
