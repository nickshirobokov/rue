"""Resource system for dependency injection."""

import contextlib
import inspect
from collections.abc import AsyncGenerator, Generator, Iterator, Sequence
from typing import Any, cast
from uuid import UUID

from rue.context.runtime import ResourceTransactionContext
from rue.models import Spec
from rue.patching.runtime import PatchHandle
from rue.resources.models import (
    DIGraph,
    LoadedResourceDef,
    ResourceSpec,
    Scope,
)
from rue.resources.registry import ResourceRegistry
from rue.resources.state import (
    ResolverExecutionContext,
    ResolverScopeOwner,
    ResolverState,
    ResourceCacheKey,
    ResourceTeardownRecord,
)
from rue.resources.transfer import ResourceTransfer


_MAIN_SYNC_ACTOR_ID = 0
_DIRECT_EXECUTION_ID = UUID(int=0)


class ResourceResolver:
    """Resolves and caches resources for test execution."""

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        state: ResolverState | None = None,
        scope_context: ResolverExecutionContext | None = None,
        sync_actor_id: int = _MAIN_SYNC_ACTOR_ID,
    ) -> None:
        self.registry = registry
        self.state = state or ResolverState.main(sync_actor_id=sync_actor_id)
        self._scope_context = scope_context
        self.transfer = ResourceTransfer(self)

    @property
    def cached_resources(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return self.state.cached_resources_by_spec()

    @property
    def scope_context(self) -> ResolverExecutionContext | None:
        """Return the execution context bound to this resolver view."""
        return self._scope_context

    def view_for_test(
        self,
        execution_id: UUID,
        consumer_spec: Spec,
    ) -> "ResourceResolver":
        """Return a scoped resolver view for one consumer execution."""
        return ResourceResolver(
            self.registry,
            state=self.state,
            scope_context=ResolverExecutionContext.from_consumer(
                execution_id,
                consumer_spec,
            ),
        )

    @contextlib.contextmanager
    def open_transaction(
        self,
        *,
        consumer_spec: Spec,
        provider_spec: Spec,
        direct_dependencies: tuple[ResourceSpec, ...] = (),
    ) -> Iterator[None]:
        """Bind consumer/provider attribution for resolver-owned work."""
        with ResourceTransactionContext(
            consumer_spec=consumer_spec,
            provider_spec=provider_spec,
            resolver=self,
            direct_dependencies=direct_dependencies,
        ):
            yield

    def register_patch(self, handle: PatchHandle) -> None:
        """Attach a patch handle to the resolver that owns its lifetime."""
        self.state.register_patch(handle)

    async def resolve_test_deps(
        self,
        execution_id: UUID,
        params: dict[str, Any],
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> dict[str, Any]:
        """Resolve all resources needed by one compiled test."""
        graph = self.registry.graph
        kwargs = dict(params)
        for spec in graph.autouse_by_execution_id[execution_id]:
            await self.resolve_resource(
                spec,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        for name, spec in graph.injections_by_execution_id[
            execution_id
        ].items():
            kwargs[name] = await self.resolve_resource(
                spec,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            )
        return kwargs

    async def resolve_resource(
        self,
        spec: ResourceSpec,
        *,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
        scope_context: ResolverExecutionContext | None = None,
    ) -> Any:
        """Resolve one concrete resource identity from a compiled graph."""
        graph = self.registry.graph
        definition = self.registry.get_definition(spec)
        direct_dependencies = graph.dependencies_by_resource[spec]
        scope_context = scope_context or self._scope_context_for(consumer_spec)
        key = self.state.cache_key_for(spec, scope_context)
        value = await self.state.get_or_create_instance(
            key,
            lambda: self._resolve_uncached(
                graph=graph,
                key=key,
                consumer_spec=consumer_spec,
                scope_context=scope_context,
            ),
        )

        if not apply_injection_hook:
            return value

        with self.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            direct_dependencies=direct_dependencies,
        ):
            return await self._apply_hook(
                definition.on_injection,
                spec.name,
                value,
            )

    async def teardown(self) -> None:
        """Tear down resources and patches owned by this resolver."""
        teardown_errors: list[Exception] = []
        for owner in reversed(tuple(self.state.scope_owners())):
            if self.state.is_shadow:
                self.state.clear_scope_owner(owner)
                self._undo_patches(owner)
                continue
            teardown_errors.extend(
                await self._run_teardowns(
                    self.state.pop_teardown_records(owner)
                )
            )
            self.state.clear_scope_owner(owner)
            self._undo_patches(owner)
        self._raise_teardown_errors(teardown_errors)

    async def _run_teardowns(
        self,
        teardowns: Sequence[ResourceTeardownRecord],
    ) -> list[Exception]:
        teardown_errors: list[Exception] = []

        for teardown in reversed(teardowns):
            spec = teardown.key.spec
            with self.open_transaction(
                consumer_spec=teardown.consumer_spec,
                provider_spec=spec,
                direct_dependencies=teardown.direct_dependencies,
            ):
                try:
                    if teardown.definition.is_async_generator:
                        await anext(
                            cast(
                                "AsyncGenerator[Any, None]",
                                teardown.generator,
                            ),
                            None,
                        )
                    else:
                        next(
                            cast(
                                "Generator[Any, None, None]",
                                teardown.generator,
                            ),
                            None,
                        )
                except Exception as e:
                    teardown_errors.append(
                        RuntimeError(
                            "Generator teardown failed for resource "
                            f"'{spec.name}': {e}"
                        )
                    )

                if self.state.has_cached_instance(teardown.key):
                    value = self.state.cached_instance(teardown.key)
                    try:
                        await self._apply_hook(
                            teardown.definition.on_teardown,
                            spec.name,
                            value,
                        )
                    except RuntimeError as e:
                        teardown_errors.append(e)
        return teardown_errors

    @staticmethod
    def _raise_teardown_errors(teardown_errors: list[Exception]) -> None:
        match teardown_errors:
            case []:
                return
            case [error]:
                raise RuntimeError(error)
            case _:
                raise ExceptionGroup(
                    "Teardown errors occurred", teardown_errors
                )

    async def teardown_scope(self, scope: Scope) -> None:
        """Teardown only resources matching the given scope."""
        teardown_errors: list[Exception] = []
        for owner in self._scope_owners_to_teardown(scope):
            if self.state.is_shadow:
                self.state.clear_scope_owner(owner)
                self._undo_patches(owner)
                continue
            teardown_errors.extend(
                await self._run_teardowns(
                    self.state.pop_teardown_records(owner)
                )
            )
            self.state.clear_scope_owner(owner)
            self._undo_patches(owner)
        self._raise_teardown_errors(teardown_errors)

    def _scope_owners_to_teardown(
        self, scope: Scope
    ) -> tuple[ResolverScopeOwner, ...]:
        if self._scope_context is None:
            return self.state.scope_owners_for(scope)
        return (
            ResolverScopeOwner.for_resource_scope(scope, self._scope_context),
        )

    def _undo_patches(self, owner: ResolverScopeOwner) -> None:
        for handle in reversed(self.state.pop_patch_handles(owner)):
            handle.undo()

    async def _resolve_uncached(
        self,
        *,
        graph: DIGraph,
        key: ResourceCacheKey,
        consumer_spec: Spec,
        scope_context: ResolverExecutionContext,
    ) -> Any:
        spec = key.spec
        definition = self.registry.get_definition(spec)
        direct_dependencies = graph.dependencies_by_resource[spec]
        with self.open_transaction(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            direct_dependencies=direct_dependencies,
        ):
            kwargs = {
                dependency.name: (
                    await self.resolve_resource(
                        dependency,
                        consumer_spec=spec,
                        scope_context=scope_context,
                    )
                )
                for dependency in direct_dependencies
            }

            match definition:
                case LoadedResourceDef(is_async_generator=True):
                    async_generator = cast(
                        "AsyncGenerator[Any, None]", definition.fn(**kwargs)
                    )
                    value = await anext(async_generator)
                    self.state.record_teardown(
                        ResourceTeardownRecord(
                            key=key,
                            definition=definition,
                            generator=async_generator,
                            consumer_spec=consumer_spec,
                            direct_dependencies=direct_dependencies,
                        )
                    )
                case LoadedResourceDef(is_generator=True):
                    generator = cast(
                        "Generator[Any, None, None]", definition.fn(**kwargs)
                    )
                    value = next(generator)
                    self.state.record_teardown(
                        ResourceTeardownRecord(
                            key=key,
                            definition=definition,
                            generator=generator,
                            consumer_spec=consumer_spec,
                            direct_dependencies=direct_dependencies,
                        )
                    )
                case LoadedResourceDef(is_async=True):
                    value = await definition.fn(**kwargs)
                case _:
                    value = definition.fn(**kwargs)

            value = await self._apply_hook(
                definition.on_resolve,
                spec.name,
                value,
            )

        return value

    def _scope_context_for(
        self, consumer_spec: Spec
    ) -> ResolverExecutionContext:
        if self._scope_context is not None:
            return self._scope_context
        return ResolverExecutionContext.from_consumer(
            _DIRECT_EXECUTION_ID, consumer_spec
        )

    async def _apply_hook(
        self, hook: Any, resource_name: str, value: Any
    ) -> Any:
        if hook is None:
            return value

        try:
            value = hook(value)
            if inspect.isawaitable(value):
                value = await value
        except Exception as e:
            msg = (
                f"Hook {hook.__name__} failed for resource "
                f"'{resource_name}': {e}"
            )
            raise RuntimeError(msg) from e
        return value
