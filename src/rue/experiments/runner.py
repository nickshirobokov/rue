"""Experiment runner."""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from uuid import uuid4

from rue.config import Config
from rue.context.runtime import CURRENT_RUN_ID, bind
from rue.experiments.models import (
    ExperimentSpec,
    ExperimentVariant,
    ExperimentVariantResult,
)
from rue.experiments.registry import registry as default_experiment_registry
from rue.resources import ResourceResolver
from rue.resources.registry import registry as default_resource_registry
from rue.testing.discovery import TestLoader
from rue.testing.models import Run
from rue.testing.models.spec import TestSpecCollection
from rue.testing.runner import Runner


@dataclass(slots=True)
class ExperimentRunner:
    """Runs experiment variants as isolated processes."""

    config: Config
    fail_fast: bool = False
    capture_output: bool = True

    def collect(
        self, collection: TestSpecCollection
    ) -> tuple[ExperimentSpec, ...]:
        """Load setup files and return registered experiments."""
        default_resource_registry.reset()
        default_experiment_registry.reset()
        loader = TestLoader(collection.suite_root)
        for setup_ref in collection.all_setup_files:
            loader.prepare_setup(setup_ref.path)
        return default_experiment_registry.all()

    def run(
        self,
        collection: TestSpecCollection,
        experiments: tuple[ExperimentSpec, ...] | None = None,
    ) -> tuple[ExperimentVariantResult, ...]:
        """Run baseline plus every experiment value combination."""
        experiment_specs = (
            self.collect(collection) if experiments is None else experiments
        )
        if not experiment_specs:
            return ()

        results: list[ExperimentVariantResult] = []
        variants = ExperimentVariant.build_all(experiment_specs)
        with ProcessPoolExecutor(
            max_workers=1,
            max_tasks_per_child=1,
        ) as pool:
            for variant in variants:
                future = pool.submit(
                    run_experiment_variant,
                    collection,
                    variant,
                    self.config,
                    self.fail_fast,
                    self.capture_output,
                )
                results.append(future.result())
        return tuple(results)


def run_experiment_variant(
    collection: TestSpecCollection,
    variant: ExperimentVariant,
    config: Config,
    fail_fast: bool,
    capture_output: bool,
) -> ExperimentVariantResult:
    """Process entrypoint for one experiment variant."""
    return asyncio.run(
        _run_experiment_variant(
            collection,
            variant,
            config,
            fail_fast,
            capture_output,
        )
    )


async def _run_experiment_variant(
    collection: TestSpecCollection,
    variant: ExperimentVariant,
    config: Config,
    fail_fast: bool,
    capture_output: bool,
) -> ExperimentVariantResult:
    default_resource_registry.reset()
    default_experiment_registry.reset()
    loader = TestLoader(collection.suite_root)
    for setup_ref in collection.all_setup_files:
        loader.prepare_setup(setup_ref.path)

    run_id = uuid4()
    resolver = ResourceResolver(default_resource_registry)
    run = None
    with bind(CURRENT_RUN_ID, run_id):
        try:
            await variant.apply(
                default_experiment_registry.all(),
                resolver=resolver,
                run_id=run_id,
            )
            items = loader.load_from_collection(collection)
            runner = Runner(
                config=config,
                reporters=[],
                fail_fast=fail_fast,
                capture_output=capture_output,
                experiment_variant=variant,
                experiment_setup_chain=collection.all_setup_files,
            )
            run = await runner.run(items, resolver=resolver, run_id=run_id)
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
