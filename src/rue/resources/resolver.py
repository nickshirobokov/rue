"""Resource system for dependency injection."""

from collections.abc import AsyncGenerator, Generator, Sequence
from typing import Any, cast

from rue.context.models import ScopeOwner
from rue.context.runtime import CURRENT_TEST, ResourceHookContext
from rue.context.scopes import Scope, ScopeContext
from rue.models import Spec
from rue.patching.runtime import PatchStore
from rue.resources.models import (
    ResourceFactoryKind,
    ResourceGraph,
    ResourceSpec,
    ScheduledTeardown,
)
from rue.resources.registry import ResourceRegistry
from rue.resources.store import ResourceStore
from rue.resources.transfer import StateTransfer


_MAIN_SYNC_ACTOR_ID = 0


class DependencyResolver:
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
        self.transfer = StateTransfer(self)

    async def resolve_graph_deps(
        self,
        graph: ResourceGraph,
        params: dict[str, Any],
        *,
        consumer_spec: Spec,
        preload: bool = False,
    ) -> dict[str, Any]:
        """Resolve all graph-bound dependencies into caller kwargs.

        With ``preload=True``, materialize everything without injection hooks;
        snapshot/export paths return an empty dict and ignore ``params``.
        """
        with self.patches:
            apply_injection_hook = not preload
            kwargs: dict[str, Any] = (
                dict(params) if apply_injection_hook else {}
            )

            for spec in graph.autouse:
                await self.resolve_resource(
                    spec,
                    graph=graph,
                    consumer_spec=consumer_spec,
                    apply_injection_hook=apply_injection_hook,
                )
            for name, spec in graph.injections.items():
                value = await self.resolve_resource(
                    spec,
                    graph=graph,
                    consumer_spec=consumer_spec,
                    apply_injection_hook=apply_injection_hook,
                )
                if apply_injection_hook:
                    kwargs[name] = value

            return kwargs

    async def resolve_resource(
        self,
        spec: ResourceSpec,
        *,
        graph: ResourceGraph | None = None,
        consumer_spec: Spec,
        apply_injection_hook: bool = True,
    ) -> Any:
        """Resolve one concrete resource identity from a compiled graph."""
        with self.patches:
            if graph is None:
                graph = self.registry.get_graph(
                    CURRENT_TEST.get().execution_id
                )
            definition = self.registry.get_definition(spec)
            direct_dependencies = graph.dependencies[spec]
            owner = ScopeContext.current_owner(spec.scope)
            if self.resources.has(spec, owner):
                value = self.resources.get(spec, owner)
            elif self.resources.claim_resolution(spec, owner):
                try:
                    value = await self._materialize_resource(
                        spec=spec,
                        graph=graph,
                        owner=owner,
                        consumer_spec=consumer_spec,
                        apply_injection_hook=apply_injection_hook,
                    )
                except Exception as error:
                    self.resources.fail_resolution(spec, owner, error)
                    raise
                else:
                    self.resources.commit_resolution(spec, owner, value)
            else:
                value = await self.resources.wait_resolution(spec, owner)

            if not apply_injection_hook:
                return value

            with ResourceHookContext(
                consumer_spec=consumer_spec,
                provider_spec=spec,
                direct_dependencies=direct_dependencies,
            ):
                return await definition.on_injection(value)

    async def teardown(self, scope: Scope | None = None) -> None:
        """Tear down resources and patches owned by this resolver."""
        with self.patches:
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

    async def _materialize_resource(
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
                    ScheduledTeardown(
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
                    ScheduledTeardown(
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

        with ResourceHookContext(
            consumer_spec=consumer_spec,
            provider_spec=spec,
            direct_dependencies=direct_dependencies,
        ):
            value = await definition.on_resolve(value)

        return value

    async def _run_teardowns(
        self,
        teardowns: Sequence[ScheduledTeardown],
    ) -> list[Exception]:
        teardown_errors: list[Exception] = []

        for teardown in reversed(teardowns):
            spec = teardown.spec
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
                with ResourceHookContext(
                    consumer_spec=teardown.consumer_spec,
                    provider_spec=spec,
                    direct_dependencies=teardown.direct_dependencies,
                ):
                    try:
                        await teardown.definition.on_teardown(value)
                    except Exception as e:
                        teardown_errors.append(e)
        return teardown_errors
