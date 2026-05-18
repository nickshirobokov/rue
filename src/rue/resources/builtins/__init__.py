"""Builtin resources registered by Rue itself."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable

from rue.context.runtime import (
    SUITE_EXECUTION_CONTEXT,
)
from rue.context.scopes import CurrentProcessKind, Scope, ScopeContext
from rue.environment.env import Environment
from rue.environment.storage import EnvironmentStorage
from rue.environment.sync import EnvironmentSyncState
from rue.patching import MonkeyPatch
from rue.resources.registry import ResourceRegistry
from rue.resources.sync import SyncableResource, SyncState


def register_builtin_resources(registry: ResourceRegistry) -> None:
    """Register framework-provided resources into the given registry."""
    SyncableResource.register(Environment)
    SyncState.register(EnvironmentSyncState)

    def scoped_monkeypatch(scope: Scope) -> Callable[[], MonkeyPatch]:
        def monkeypatch() -> MonkeyPatch:
            return MonkeyPatch.for_scope(scope)

        return monkeypatch

    def environment_factory(
        scope: Scope,
    ) -> Callable[[], AsyncGenerator[Environment, None]]:
        async def environment() -> AsyncGenerator[Environment, None]:
            suite_context = SUITE_EXECUTION_CONTEXT.get()
            owner = ScopeContext.current_owner(scope)
            storage = EnvironmentStorage()
            root = storage.allocate(
                suite_context.suite_execution_id,
                owner,
                process_kind=suite_context.process,
            )
            env = Environment(root=root, scope=scope)
            try:
                yield env
            finally:
                if not (
                    suite_context.process is CurrentProcessKind.TEST_SUBPROCESS
                    and scope in {Scope.MODULE, Scope.SUITE}
                ):
                    storage.release(root)

        environment.__name__ = "environment"
        environment.__qualname__ = "environment"
        return environment

    for scope in Scope:
        registry.register_resource(
            scoped_monkeypatch(scope),
            scope=scope,
            builtin=True,
        )
        registry.register_resource(
            environment_factory(scope),
            scope=scope,
            builtin=True,
            subprocess_sync=True,
        )
