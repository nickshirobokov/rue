"""Experiment runtime application."""

from __future__ import annotations

from uuid import UUID

from rue.experiments.models import ExperimentVariant
from rue.resources.registry import ResourceRegistry
from rue.resources.resolver import ResourceResolver


async def apply_experiment_variant(
    variant: ExperimentVariant,
    *,
    registry: ResourceRegistry,
    resolver: ResourceResolver,
    run_id: UUID,
) -> None:
    """Apply selected experiment hooks to the current run process."""
    definitions = {
        definition.experiment.name: definition
        for definition in registry.experiments()
        if definition.experiment is not None
    }
    for name, value_index, _value_id in variant.values:
        definition = definitions[name]
        experiment = definition.experiment
        if experiment is not None:
            await resolver.apply_experiment(
                definition,
                experiment.value_at(value_index),
                run_id=run_id,
            )
