"""Tests for CRDT-backed resource sync helpers."""

from __future__ import annotations

import inspect
import threading
from contextvars import ContextVar
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel

from rue.resources import (
    ResolverSyncSnapshot,
    DIGraph,
    ResourceResolver,
    Scope,
    resource,
    registry,
)
from rue.resources.snapshot import SyncGraph
from tests.unit.factories import make_definition


_TEST_GRAPH_KEY = UUID(int=1)


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


class SlotsState:
    __slots__ = ("_cache", "_private", "count", "ctx", "lock")

    def __init__(self) -> None:
        self.count = 1
        self._private = "secret"
        self._cache = {"skip": True}
        self.lock = threading.Lock()
        self.ctx = ContextVar("slots_state_ctx", default=0)
        self.ctx.set(5)


class FrameworkLike:
    __slots__ = ("__runtime__", "_cache", "count", "name")
    __signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "name",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
            inspect.Parameter(
                "count",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
        ],
    )

    def __init__(self, name: str, count: int) -> None:
        self.name = name
        self.count = count
        self._cache = {"skip": True}
        self.__runtime__ = "skip"


class BaseHousekeeping:
    __slots__ = ("__helper__", "_cache")

    def __init__(self) -> None:
        self.__helper__ = "selected"
        self._cache = {"skip": True}


class InheritedHousekeepingState(BaseHousekeeping):
    __slots__ = ("count",)
    __match_args__ = ("count", "__helper__")

    def __init__(self) -> None:
        super().__init__()
        self.count = 1


class Box:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


class AttrState:
    def __init__(self) -> None:
        self.left = "base-left"
        self.right = "base-right"


class BranchHolder:
    def __init__(self) -> None:
        self.branch = AttrState()


class NestedHolder:
    def __init__(self) -> None:
        self.payload = {"items": [Box(1), Box(2)]}


def _snapshot_payload(snapshot: ResolverSyncSnapshot) -> dict[str, object]:
    graph = SyncGraph.from_update(snapshot.graph_update, actor_id=0)
    return graph.payload(
        identity.snapshot_key for identity in snapshot.resource_specs
    )


def _consumer_spec(module_path: Path | None = None):
    return make_definition("test_transfer", module_path=module_path or "test.py").spec


def _resource_graph(
    resource_names: tuple[str, ...],
    *,
    consumer_spec=None,
    key: UUID = _TEST_GRAPH_KEY,
) -> DIGraph:
    consumer = consumer_spec or _consumer_spec()
    return registry.compile_di_graph({key: (consumer, resource_names)})


async def _resolve(
    resolver: ResourceResolver,
    name: str,
    *,
    consumer_spec=None,
):
    consumer = consumer_spec or _consumer_spec()
    graph = _resource_graph((name,), consumer_spec=consumer)
    return await resolver.resolve_resource(
        graph.injections_by_execution_id[_TEST_GRAPH_KEY][name],
        consumer_spec=consumer,
    )


def _snapshot(
    resolver: ResourceResolver,
    resource_names: tuple[str, ...],
    *,
    consumer_spec=None,
    sync_actor_id: int = 1,
) -> ResolverSyncSnapshot:
    _resource_graph(resource_names, consumer_spec=consumer_spec)
    return resolver.export_sync_snapshot(
        _TEST_GRAPH_KEY,
        sync_actor_id=sync_actor_id,
    )


def _sync_update(
    resolver: ResourceResolver,
    snapshot: ResolverSyncSnapshot,
) -> bytes:
    return resolver.sync_update_for_resources_since(
        snapshot.base_state,
        list(snapshot.resource_specs),
    )


def _apply_worker_update(
    parent: ResourceResolver,
    worker: ResourceResolver,
    snapshot: ResolverSyncSnapshot,
) -> None:
    parent.apply_sync_update(snapshot, _sync_update(worker, snapshot))


class TestExportSyncSnapshot:
    async def test_includes_test_scope_in_snapshot_closure(self):
        @resource(scope=Scope.TEST)
        def per_test():
            return {"kind": "test"}

        @resource(scope=Scope.RUN)
        def shared():
            return {"kind": "run"}

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "shared", consumer_spec=_consumer_spec())
        await _resolve(resolver, "per_test", consumer_spec=_consumer_spec())

        snapshot = _snapshot(
            resolver,
            ("shared", "per_test"),
            consumer_spec=_consumer_spec(),
        )

        names = {
            identity.locator.function_name for identity in snapshot.resource_specs
        }
        payload = _snapshot_payload(snapshot)

        assert names == {"shared", "per_test"}
        assert set(payload["root_ids"]) == {
            identity.snapshot_key for identity in snapshot.resource_specs
        }

    async def test_records_ignored_runtime_fields(self):
        @resource(scope=Scope.RUN)
        def state():
            return SlotsState()

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "state", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("state",), consumer_spec=_consumer_spec())
        identity = snapshot.resource_specs[0]
        payload = _snapshot_payload(snapshot)
        root_node = payload["nodes"][payload["root_ids"][identity.snapshot_key]]
        attrs = set(root_node["attrs"])

        assert "count" in attrs
        assert "_private" in attrs
        assert "_cache" not in attrs
        assert "lock" not in attrs
        assert payload["ignored_paths"][identity.snapshot_key] == [
            "_cache",
            "lock",
        ]

    async def test_framework_like_state_uses_declared_surface(self):
        @resource(scope=Scope.RUN)
        def state():
            return FrameworkLike("demo", 3)

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "state", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("state",), consumer_spec=_consumer_spec())
        identity = snapshot.resource_specs[0]
        payload = _snapshot_payload(snapshot)
        root_node = payload["nodes"][payload["root_ids"][identity.snapshot_key]]

        assert set(root_node["attrs"]) == {"name", "count"}
        assert set(payload["ignored_paths"][identity.snapshot_key]) == {
            "__runtime__",
            "_cache",
        }

    async def test_parent_slots_need_semantic_surface_to_escape_ignores(self):
        @resource(scope=Scope.RUN)
        def state():
            return InheritedHousekeepingState()

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "state", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("state",), consumer_spec=_consumer_spec())
        identity = snapshot.resource_specs[0]
        payload = _snapshot_payload(snapshot)
        root_node = payload["nodes"][payload["root_ids"][identity.snapshot_key]]

        assert set(root_node["attrs"]) == {"count", "__helper__"}
        assert payload["ignored_paths"][identity.snapshot_key] == ["_cache"]

    async def test_pydantic_model_syncs_fields_without_package_branches(self):
        class Model(BaseModel):
            name: str
            count: int

        @resource(scope=Scope.RUN)
        def state():
            return Model(name="demo", count=3)

        resolver = ResourceResolver(registry)
        live = await _resolve(resolver, "state", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("state",), consumer_spec=_consumer_spec())
        identity = snapshot.resource_specs[0]
        payload = _snapshot_payload(snapshot)
        root_node = payload["nodes"][payload["root_ids"][identity.snapshot_key]]
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_state = await _resolve(
            worker,
            "state",
            consumer_spec=_consumer_spec(),
        )
        worker_state.count = 8

        _apply_worker_update(resolver, worker, snapshot)

        assert set(root_node["attrs"]) == {"name", "count"}
        assert {
            "__pydantic_extra__",
            "__pydantic_fields_set__",
            "__pydantic_private__",
        } <= set(payload["ignored_paths"][identity.snapshot_key])
        assert live.count == 8

    async def test_preserves_shared_reference_nodes(self):
        @resource(scope=Scope.RUN)
        def shared():
            return {"value": 1}

        @resource(scope=Scope.RUN)
        def alias(shared):
            return shared

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "alias", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("alias",), consumer_spec=_consumer_spec())
        payload = _snapshot_payload(snapshot)
        identity_map = {
            identity.locator.function_name: identity
            for identity in snapshot.resource_specs
        }

        assert (
            payload["root_ids"][identity_map["shared"].snapshot_key]
            == payload["root_ids"][identity_map["alias"].snapshot_key]
        )

    async def test_resource_graph_and_actor_are_stored(self):
        @resource(scope=Scope.RUN)
        def simple():
            return 1

        resolver = ResourceResolver(registry)
        consumer_spec = _consumer_spec(
            module_path=Path("/project/tests/test_foo.py")
        )
        await _resolve(resolver, "simple", consumer_spec=consumer_spec)

        snapshot = _snapshot(
            resolver,
            ("simple",),
            consumer_spec=consumer_spec,
            sync_actor_id=7,
        )

        assert (
            snapshot.execution_graph.roots_by_execution_id[_TEST_GRAPH_KEY][0].name
            == "simple"
        )
        assert snapshot.actor_id == 7

    async def test_atomic_values_use_tagged_nodes(self):
        class Mode(Enum):
            FAST = "fast"

        @resource(scope=Scope.RUN)
        def state():
            return {
                "uuid": UUID("12345678-1234-5678-1234-567812345678"),
                "path": Path("/tmp/demo"),
                "date": date(2024, 1, 2),
                "datetime": datetime(
                    2024,
                    1,
                    2,
                    3,
                    4,
                    5,
                    tzinfo=UTC,
                ),
                "time": time(3, 4, 5),
                "delta": timedelta(seconds=7),
                "enum": Mode.FAST,
            }

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "state", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("state",), consumer_spec=_consumer_spec())
        identity = snapshot.resource_specs[0]
        payload = _snapshot_payload(snapshot)
        root_node = payload["nodes"][payload["root_ids"][identity.snapshot_key]]
        node_kinds = {
            payload["nodes"][value_id]["kind"]
            for key_id, value_id in root_node["entries"]
        }

        assert node_kinds == {
            "uuid",
            "path",
            "date",
            "datetime",
            "time",
            "timedelta",
            "enum",
        }

    def test_export_requires_cached_resources(self):
        resolver = ResourceResolver(registry)
        with pytest.raises(ValueError, match="nonexistent"):
            _snapshot(
                resolver,
                ("nonexistent",),
                consumer_spec=_consumer_spec(),
            )


class TestHydrateFromSyncSnapshot:
    async def test_worker_replays_shadow_factories(self):
        resolve_count = 0

        @resource(scope=Scope.RUN)
        def config():
            nonlocal resolve_count
            resolve_count += 1
            return {"key": "value"}

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "config", consumer_spec=_consumer_spec())
        assert resolve_count == 1

        snapshot = _snapshot(resolver, ("config",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )

        assert resolve_count == 2
        assert await _resolve(worker, "config", consumer_spec=_consumer_spec()) == {
            "key": "value"
        }

    async def test_worker_applies_parent_state_over_shadow_defaults(self):
        @resource(scope=Scope.RUN)
        def shared():
            return {"count": 0}

        resolver = ResourceResolver(registry)
        shared_state = await _resolve(
            resolver,
            "shared",
            consumer_spec=_consumer_spec(),
        )
        shared_state["count"] = 4

        snapshot = _snapshot(resolver, ("shared",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )

        assert await _resolve(worker, "shared", consumer_spec=_consumer_spec()) == {
            "count": 4
        }

    async def test_worker_hydrates_contextvar_values(self):
        class Holder:
            def __init__(self) -> None:
                self.ctx = ContextVar("holder_ctx", default=0)
                self.ctx.set(7)

        @resource(scope=Scope.RUN)
        def holder():
            return Holder()

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "holder", consumer_spec=_consumer_spec())

        snapshot = _snapshot(resolver, ("holder",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        hydrated = await _resolve(worker, "holder", consumer_spec=_consumer_spec())

        assert hydrated.ctx.get() == 7

    async def test_empty_snapshot_hydration(self):
        graph = SyncGraph(actor_id=1)
        snapshot = ResolverSyncSnapshot(
            resource_specs=(),
            execution_graph=DIGraph(),
            graph_update=graph.doc.get_update(None),
            base_state=graph.doc.get_state(),
            resolution_order=(),
            actor_id=1,
        )
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )

        assert len(worker.cached_resources) == 0


class TestSyncRoundTrip:
    async def test_test_scope_updates_sync_before_parent_teardown(self):
        @resource(scope=Scope.TEST)
        def case_state():
            return {"events": []}

        parent = ResourceResolver(registry)
        forked = parent.view_for_test(UUID(int=2), _consumer_spec())
        state = await _resolve(
            forked,
            "case_state",
            consumer_spec=_consumer_spec(),
        )
        snapshot = _snapshot(
            forked,
            ("case_state",),
            consumer_spec=_consumer_spec(),
        )

        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_state = await _resolve(
            worker,
            "case_state",
            consumer_spec=_consumer_spec(),
        )
        worker_state["events"].append("worker")

        forked.apply_sync_update(snapshot, _sync_update(worker, snapshot))

        assert state["events"] == ["worker"]

    async def test_concurrent_list_appends_are_preserved(self):
        @resource(scope=Scope.RUN)
        def shared():
            return {"values": ["base"]}

        parent = ResourceResolver(registry)
        shared_state = await _resolve(parent, "shared", consumer_spec=_consumer_spec())
        snapshot = _snapshot(parent, ("shared",), consumer_spec=_consumer_spec())

        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_shared = await _resolve(
            worker,
            "shared",
            consumer_spec=_consumer_spec(),
        )

        shared_state["values"].append("parent")
        worker_shared["values"].append("worker")

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state["values"] == ["base", "parent", "worker"]

    async def test_concurrent_dict_key_updates_merge(self):
        @resource(scope=Scope.RUN)
        def shared():
            return {"base": True}

        parent = ResourceResolver(registry)
        shared_state = await _resolve(parent, "shared", consumer_spec=_consumer_spec())
        snapshot = _snapshot(parent, ("shared",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_shared = await _resolve(
            worker,
            "shared",
            consumer_spec=_consumer_spec(),
        )

        shared_state["left"] = 1
        worker_shared["right"] = 2

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state == {"base": True, "left": 1, "right": 2}

    async def test_concurrent_object_attr_updates_merge(self):
        @resource(scope=Scope.RUN)
        def shared():
            return AttrState()

        parent = ResourceResolver(registry)
        shared_state = await _resolve(parent, "shared", consumer_spec=_consumer_spec())
        snapshot = _snapshot(parent, ("shared",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_shared = await _resolve(
            worker,
            "shared",
            consumer_spec=_consumer_spec(),
        )

        shared_state.left = "parent-left"
        worker_shared.right = "worker-right"

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state.left == "parent-left"
        assert shared_state.right == "worker-right"

    async def test_replaced_object_attr_preserves_untouched_parent_state(self):
        @resource(scope=Scope.RUN)
        def shared():
            return BranchHolder()

        parent = ResourceResolver(registry)
        shared_state = await _resolve(parent, "shared", consumer_spec=_consumer_spec())
        snapshot = _snapshot(parent, ("shared",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_shared = await _resolve(
            worker,
            "shared",
            consumer_spec=_consumer_spec(),
        )

        replacement = BranchHolder().branch
        replacement.right = "worker-right"
        worker_shared.branch = replacement
        shared_state.branch.left = "parent-left"

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state.branch.left == "parent-left"
        assert shared_state.branch.right == "worker-right"

    async def test_aliased_roots_stay_aliased_after_mergeback(self):
        @resource(scope=Scope.RUN)
        def shared():
            return {"events": []}

        @resource(scope=Scope.RUN)
        def alias(shared):
            return shared

        parent = ResourceResolver(registry)
        live_shared = await _resolve(parent, "shared", consumer_spec=_consumer_spec())
        live_alias = await _resolve(parent, "alias", consumer_spec=_consumer_spec())
        snapshot = _snapshot(parent, ("alias",), consumer_spec=_consumer_spec())
        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )

        worker_alias = await _resolve(worker, "alias", consumer_spec=_consumer_spec())
        worker_alias["events"].append("worker")

        _apply_worker_update(parent, worker, snapshot)

        assert live_shared is live_alias
        assert live_shared["events"] == ["worker"]

    async def test_test_generator_teardown_mutates_parent_after_merge(self):
        @resource(scope=Scope.RUN)
        def events():
            return []

        @resource(scope=Scope.TEST)
        def case_state(events):
            state = {"events": events, "body": []}
            yield state
            events.append("teardown")

        parent = ResourceResolver(registry)
        forked = parent.view_for_test(UUID(int=2), _consumer_spec())
        state = await _resolve(
            forked,
            "case_state",
            consumer_spec=_consumer_spec(),
        )
        snapshot = _snapshot(
            forked,
            ("case_state",),
            consumer_spec=_consumer_spec(),
        )

        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_state = await _resolve(
            worker,
            "case_state",
            consumer_spec=_consumer_spec(),
        )
        worker_state["body"].append("worker")

        _apply_worker_update(forked, worker, snapshot)

        assert state["body"] == ["worker"]
        await forked.teardown_scope(Scope.TEST)
        assert await _resolve(parent, "events", consumer_spec=_consumer_spec()) == [
            "teardown"
        ]

    async def test_slots_private_fields_and_runtime_ignores_round_trip(self):
        @resource(scope=Scope.RUN)
        def state():
            return SlotsState()

        parent = ResourceResolver(registry)
        live = await _resolve(parent, "state", consumer_spec=_consumer_spec())
        snapshot = _snapshot(parent, ("state",), consumer_spec=_consumer_spec())

        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_state = await _resolve(worker, "state", consumer_spec=_consumer_spec())
        worker_state.count = 8
        worker_state._private = "worker"
        worker_state.ctx.set(11)

        _apply_worker_update(parent, worker, snapshot)

        assert live.count == 8
        assert live._private == "worker"
        assert live.ctx.get() == 11
        assert isinstance(live.lock, type(threading.Lock()))

    async def test_remote_merge_keeps_live_identity(self):
        @resource(scope=Scope.RUN)
        def holder():
            return {"items": [Box(1), Box(2)]}

        parent = ResourceResolver(registry)
        state = await _resolve(parent, "holder", consumer_spec=_consumer_spec())
        items_before = state["items"]
        snapshot = _snapshot(parent, ("holder",), consumer_spec=_consumer_spec())

        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_state = await _resolve(
            worker,
            "holder",
            consumer_spec=_consumer_spec(),
        )
        worker_state["items"].append(Box(3))

        _apply_worker_update(parent, worker, snapshot)

        assert state["items"] is items_before
        assert [box.value for box in state["items"]] == [1, 2, 3]

    async def test_nested_remote_merge_keeps_parent_identities(self):
        @resource(scope=Scope.RUN)
        def holder():
            return NestedHolder()

        parent = ResourceResolver(registry)
        state = await _resolve(parent, "holder", consumer_spec=_consumer_spec())
        payload_before = state.payload
        items_before = state.payload["items"]
        snapshot = _snapshot(parent, ("holder",), consumer_spec=_consumer_spec())

        worker = await ResourceResolver.from_sync_snapshot(
            snapshot,
            registry,
            consumer_spec=_consumer_spec(),
        )
        worker_state = await _resolve(
            worker,
            "holder",
            consumer_spec=_consumer_spec(),
        )
        worker_state.payload["items"].append(Box(3))

        _apply_worker_update(parent, worker, snapshot)

        assert state.payload is payload_before
        assert state.payload["items"] is items_before
        assert [box.value for box in state.payload["items"]] == [1, 2, 3]
