"""Builtin `environment` resource registered at every scope."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable

from rue.context.runtime import (
    RESOURCE_TRANSACTION_CONTEXT,
    SUITE_EXECUTION_CONTEXT,
)
from rue.context.scopes import Scope, ScopeContext
from rue.environment.runtime import Environment
from rue.environment.storage import EnvironmentStorage
from rue.environment.sync import EnvironmentSyncState
from rue.resources.sync import SyncableResource, SyncState


SyncableResource.register(Environment)
SyncState.register(EnvironmentSyncState)


def make_environment_factory(
    scope: Scope,
) -> Callable[[], AsyncGenerator[Environment, None]]:
    """Build the per-scope async-generator factory for `environment`.

    The factory keeps allocation cheap (a single mkdir) so that worker
    processes can re-run it without paying for materialization. Source
    materialization happens lazily inside ``Environment.load``.
    """

    async def environment() -> AsyncGenerator[Environment, None]:
        suite_context = SUITE_EXECUTION_CONTEXT.get()
        owner = ScopeContext.current_owner(scope)
        storage = EnvironmentStorage()
        root = storage.allocate(
            suite_context.suite_execution_id,
            owner,
            process_kind=suite_context.process,
        )
        env = Environment._build(root=root, scope=scope)
        try:
            yield env
        finally:
            storage.release(root)

    environment.__name__ = "environment"
    environment.__qualname__ = "environment"
    return environment


def on_resolve(env: Environment) -> Environment:
    """Stamp the provider spec onto the env for telemetry/debugging."""
    env._provider_spec = RESOURCE_TRANSACTION_CONTEXT.get().provider_spec
    return env


def on_injection(env: Environment) -> Environment:
    """Record the per-consumer baseline used by ``env.diff``."""
    consumer = RESOURCE_TRANSACTION_CONTEXT.get().consumer_spec
    env._mark_consumer_baseline(consumer)
    return env


__all__ = [
    "make_environment_factory",
    "on_injection",
    "on_resolve",
]
