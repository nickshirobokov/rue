"""Resource system for dependency injection."""

from collections.abc import AsyncGenerator, Generator, Sequence
from typing import Any, cast

from rue.context.runtime import CURRENT_TEST, ResourceTransactionContext
from rue.context.scopes import Scope, ScopeContext, ScopeOwner
from rue.models import Spec
from rue.patching.runtime import PatchLifetime, PatchStore
from rue.resources.models import (
    ResourceFactoryKind,
    ResourceGraph,
    ResourceSpec,
)
from rue.resources.registry import ResourceRegistry
from rue.resources.state import (
    ResourceStore,
    ResourceTeardownRecord,
)
from rue.resources.transfer import ResourceTransfer


_MAIN_SYNC_ACTOR_ID = 0


class ResourceResolver:
    """Resolves and caches resources for test execution."""

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        resources: ResourceStore | None = None,
        patches: PatchStore | None = None,
        sync_actor_id: int = _MAIN_SYNC_ACTOR_ID,
    ) -> None:
        self.registry = registry
        self.resources = resources or ResourceStore.main(
            sync_actor_id=sync_actor_id
        )
        self.patches = patches or PatchStore()
        self.transfer = ResourceTransfer(self)

    @property
    def cached_resources(self) -> dict[ResourceSpec, Any]:
        """Return a shallow copy of the identity-to-value cache."""
        return self.resources.cached_resources_by_spec()

    def patch_lifetime(
        self,
        scope: Scope,
    ) -> PatchLifetime:
        """Build a patch lifetime owned by this resolver's state."""
        return self.patches.lifetime(ScopeContext.current_owner(scope))

    async def resolve_graph_deps(
        self,
        graph: ResourceGraph,
        params: dict[str, Any],
        *,
        consumer_spec: Spec,
    ) -> dict[str, Any]:
        """Resolve all resources needed by one compiled dependency graph."""
        kwargs = dict(params)
        for spec in graph.autouse:
            await self.resolve_resource(
                spec,
                graph=graph,
                consumer_spec=consumer_spec,
            )
        for name, spec in graph.injections.items():
            kwargs[name] = await self.resolve_resource(
                spec,
                graph=graph,
                consumer_spec=consumer_spec,
            )
        return kwargs

    async def preload_graph(
        self,
        graph: ResourceGraph,
        *,
        consumer_spec: Spec,
    ) -> None:
        """Resolve graph dependencies without injection metadata mutation."""
        for spec in graph.autouse:
            await self.resolve_resource(
                spec,
                graph=graph,
                consumer_spec=consumer_spec,
                apply_injection_hook=False,
            )
        for spec in graph.injections.values():
            await self.resolve_resource(
                spec,
                graph=graph,
                consumer_spec=consumer_spec,
                apply_injection_hook=False,
            )

    async def resolve_resource(
        self,
        spec: ResourceSpec,
        *,
        graph: ResourceGraph | None = None,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> Any:
        """Resolve one concrete resource identity from a compiled graph."""
        if graph is None:
            graph = self.registry.get_graph(CURRENT_TEST.get().execution_id)
        definition = self.registry.get_definition(spec)
        direct_dependencies = graph.dependencies[spec]
        owner = ScopeContext.current_owner(spec.scope)
        value = await self.resources.get_or_create(
            spec,
            owner,
            lambda: self._resolve_uncached(
                spec=spec,
                graph=graph,
                owner=owner,
                consumer_spec=consumer_spec,
                apply_injection_hook=apply_injection_hook,
            ),
        )

        if not apply_injection_hook:
            return value

        with ResourceTransactionContext(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            resolver=self,
            direct_dependencies=direct_dependencies,
        ):
            return await definition.on_injection(value)

    async def teardown(self, scope: Scope | None = None) -> None:
        """Tear down resources and patches owned by this resolver."""
        teardown_errors: list[Exception] = []
        if scope is None:
            owners = tuple(reversed(tuple(self.resources.scope_owners())))
        else:
            owners = (ScopeContext.current_owner(scope),)
        for owner in owners:
            if self.resources.is_shadow:
                self.resources.clear(owner)
                self.undo_patches(owner=owner)
                continue
            teardown_errors.extend(
                await self._run_teardowns(
                    self.resources.pop_teardown_records(owner)
                )
            )
            self.resources.clear(owner)
            self.undo_patches(owner=owner)
        if scope is None:
            self.undo_patches()
        match teardown_errors:
            case []:
                pass
            case [error]:
                raise RuntimeError(error)
            case _:
                raise ExceptionGroup(
                    "Teardown errors occurred", teardown_errors
                )

    async def _run_teardowns(
        self,
        teardowns: Sequence[ResourceTeardownRecord],
    ) -> list[Exception]:
        teardown_errors: list[Exception] = []

        for teardown in reversed(teardowns):
            spec = teardown.spec
            with ResourceTransactionContext(
                consumer_spec=teardown.consumer_spec,
                provider_spec=spec,
                resolver=self,
                direct_dependencies=teardown.direct_dependencies,
            ):
                try:
                    if (
                        teardown.definition.factory_kind
                        is ResourceFactoryKind.ASYNC_GENERATOR
                    ):
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

                if self.resources.has(spec, teardown.owner):
                    value = self.resources.get(spec, teardown.owner)
                    try:
                        await teardown.definition.on_teardown(value)
                    except Exception as e:
                        teardown_errors.append(e)
        return teardown_errors

    def undo_patches(
        self,
        *,
        scope: Scope | None = None,
        owner: ScopeOwner | None = None,
    ) -> None:
        """Pop patches from the store and undo them."""
        match (owner, scope):
            case (ScopeOwner() as o, None):
                handles = reversed(self.patches.pop_owner(o))
            case (None, None):
                handles = reversed(self.patches.pop_all())
            case (None, Scope.TEST | Scope.MODULE | Scope.RUN):
                handles = reversed(self.patches.pop_scope(scope))
            case (ScopeOwner() as o, Scope.TEST | Scope.MODULE | Scope.RUN):
                msg = "Owner and scope cannot both be specified."
                raise ValueError(msg)
        for handle in handles:
            handle.undo()

    async def _resolve_uncached(
        self,
        *,
        spec: ResourceSpec,
        graph: ResourceGraph,
        owner: ScopeOwner,
        consumer_spec: Spec,
        apply_injection_hook: bool,
    ) -> Any:
        definition = self.registry.get_definition(spec)
        direct_dependencies = graph.dependencies[spec]
        with ResourceTransactionContext(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            resolver=self,
            direct_dependencies=direct_dependencies,
        ):
            kwargs = {
                dependency.name: await self.resolve_resource(
                    dependency,
                    graph=graph,
                    consumer_spec=spec,
                    apply_injection_hook=apply_injection_hook,
                )
                for dependency in direct_dependencies
            }

            match definition.factory_kind:
                case ResourceFactoryKind.ASYNC_GENERATOR:
                    async_generator = cast(
                        "AsyncGenerator[Any, None]", definition.fn(**kwargs)
                    )
                    value = await anext(async_generator)
                    self.resources.record_teardown(
                        ResourceTeardownRecord(
                            spec=spec,
                            owner=owner,
                            definition=definition,
                            generator=async_generator,
                            consumer_spec=consumer_spec,
                            direct_dependencies=direct_dependencies,
                        )
                    )
                case ResourceFactoryKind.GENERATOR:
                    generator = cast(
                        "Generator[Any, None, None]", definition.fn(**kwargs)
                    )
                    value = next(generator)
                    self.resources.record_teardown(
                        ResourceTeardownRecord(
                            spec=spec,
                            owner=owner,
                            definition=definition,
                            generator=generator,
                            consumer_spec=consumer_spec,
                            direct_dependencies=direct_dependencies,
                        )
                    )
                case ResourceFactoryKind.ASYNC:
                    value = await definition.fn(**kwargs)
                case ResourceFactoryKind.SYNC:
                    value = definition.fn(**kwargs)

            value = await definition.on_resolve(value)

        return value
