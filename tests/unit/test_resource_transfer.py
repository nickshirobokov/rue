"""Tests for CRDT-backed resource sync helpers."""

from __future__ import annotations

import threading
from contextvars import ContextVar
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest

from rue.resources import (
    ResolverSyncSnapshot,
    ResourceResolver,
    Scope,
    registry,
    resource,
)
from rue.resources.snapshot import SyncGraph


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


class Box:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


class AttrState:
    def __init__(self) -> None:
        self.left = "base-left"
        self.right = "base-right"


def _snapshot_payload(snapshot: ResolverSyncSnapshot) -> dict[str, object]:
    graph = SyncGraph.from_update(snapshot.graph_update, actor_id=0)
    return graph.payload(
        identity.snapshot_key for identity in snapshot.res_specs
    )


def _sync_update(
    resolver: ResourceResolver,
    snapshot: ResolverSyncSnapshot,
) -> bytes:
    return resolver.sync_update_since(
        snapshot.base_state,
        list(snapshot.res_specs),
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

        @resource(scope=Scope.PROCESS)
        def shared():
            return {"kind": "process"}

        resolver = ResourceResolver(registry)
        await resolver.resolve("shared")
        await resolver.resolve("per_test")

        snapshot = resolver.export_sync_snapshot(
            ["shared", "per_test"],
            sync_actor_id=1,
        )

        names = {identity.name for identity in snapshot.res_specs}
        payload = _snapshot_payload(snapshot)

        assert names == {"shared", "per_test"}
        assert set(payload["root_ids"]) == {
            identity.snapshot_key for identity in snapshot.res_specs
        }

    async def test_records_ignored_runtime_fields(self):
        @resource(scope=Scope.PROCESS)
        def state():
            return SlotsState()

        resolver = ResourceResolver(registry)
        await resolver.resolve("state")

        snapshot = resolver.export_sync_snapshot(["state"], sync_actor_id=1)
        identity = snapshot.res_specs[0]
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

    async def test_preserves_shared_reference_nodes(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"value": 1}

        @resource(scope=Scope.PROCESS)
        def alias(shared):
            return shared

        resolver = ResourceResolver(registry)
        await resolver.resolve("alias")

        snapshot = resolver.export_sync_snapshot(["alias"], sync_actor_id=1)
        payload = _snapshot_payload(snapshot)
        identity_map = {
            identity.name: identity for identity in snapshot.res_specs
        }

        assert (
            payload["root_ids"][identity_map["shared"].snapshot_key]
            == payload["root_ids"][identity_map["alias"].snapshot_key]
        )

    async def test_request_path_and_actor_are_stored(self):
        @resource(scope=Scope.PROCESS)
        def simple():
            return 1

        resolver = ResourceResolver(registry)
        await resolver.resolve("simple")

        snapshot = resolver.export_sync_snapshot(
            ["simple"],
            request_path=Path("/project/tests/test_foo.py"),
            sync_actor_id=7,
        )

        assert snapshot.request_path == "/project/tests/test_foo.py"
        assert snapshot.sync_actor_id == 7

    async def test_atomic_values_use_tagged_nodes(self):
        class Mode(Enum):
            FAST = "fast"

        @resource(scope=Scope.PROCESS)
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
        await resolver.resolve("state")

        snapshot = resolver.export_sync_snapshot(["state"], sync_actor_id=1)
        identity = snapshot.res_specs[0]
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
            resolver.export_sync_snapshot(["nonexistent"], sync_actor_id=1)


class TestHydrateFromSyncSnapshot:
    async def test_worker_replays_shadow_factories(self):
        resolve_count = 0

        @resource(scope=Scope.PROCESS)
        def config():
            nonlocal resolve_count
            resolve_count += 1
            return {"key": "value"}

        resolver = ResourceResolver(registry)
        await resolver.resolve("config")
        assert resolve_count == 1

        snapshot = resolver.export_sync_snapshot(["config"], sync_actor_id=1)
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )

        assert resolve_count == 2
        assert await worker.resolve("config") == {"key": "value"}

    async def test_worker_applies_parent_state_over_shadow_defaults(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"count": 0}

        resolver = ResourceResolver(registry)
        shared_state = await resolver.resolve("shared")
        shared_state["count"] = 4

        snapshot = resolver.export_sync_snapshot(["shared"], sync_actor_id=1)
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )

        assert await worker.resolve("shared") == {"count": 4}

    async def test_worker_hydrates_contextvar_values(self):
        class Holder:
            def __init__(self) -> None:
                self.ctx = ContextVar("holder_ctx", default=0)
                self.ctx.set(7)

        @resource(scope=Scope.PROCESS)
        def holder():
            return Holder()

        resolver = ResourceResolver(registry)
        await resolver.resolve("holder")

        snapshot = resolver.export_sync_snapshot(["holder"], sync_actor_id=1)
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        hydrated = await worker.resolve("holder")

        assert hydrated.ctx.get() == 7

    async def test_empty_snapshot_hydration(self):
        graph = SyncGraph(actor_id=1)
        snapshot = ResolverSyncSnapshot(
            res_specs=(),
            request_path=None,
            graph_update=graph.doc.get_update(None),
            base_state=graph.doc.get_state(),
            sync_actor_id=1,
        )
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )

        assert len(worker.cached_identities) == 0


class TestSyncRoundTrip:
    async def test_concurrent_list_appends_are_preserved(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"values": ["base"]}

        parent = ResourceResolver(registry)
        shared_state = await parent.resolve("shared")
        snapshot = parent.export_sync_snapshot(["shared"], sync_actor_id=1)

        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        worker_shared = await worker.resolve("shared")

        shared_state["values"].append("parent")
        worker_shared["values"].append("worker")

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state["values"] == ["base", "parent", "worker"]

    async def test_concurrent_dict_key_updates_merge(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"base": True}

        parent = ResourceResolver(registry)
        shared_state = await parent.resolve("shared")
        snapshot = parent.export_sync_snapshot(["shared"], sync_actor_id=1)
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        worker_shared = await worker.resolve("shared")

        shared_state["left"] = 1
        worker_shared["right"] = 2

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state == {"base": True, "left": 1, "right": 2}

    async def test_concurrent_object_attr_updates_merge(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return AttrState()

        parent = ResourceResolver(registry)
        shared_state = await parent.resolve("shared")
        snapshot = parent.export_sync_snapshot(["shared"], sync_actor_id=1)
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        worker_shared = await worker.resolve("shared")

        shared_state.left = "parent-left"
        worker_shared.right = "worker-right"

        _apply_worker_update(parent, worker, snapshot)

        assert shared_state.left == "parent-left"
        assert shared_state.right == "worker-right"

    async def test_aliased_roots_stay_aliased_after_mergeback(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"events": []}

        @resource(scope=Scope.PROCESS)
        def alias(shared):
            return shared

        parent = ResourceResolver(registry)
        live_shared = await parent.resolve("shared")
        live_alias = await parent.resolve("alias")
        snapshot = parent.export_sync_snapshot(["alias"], sync_actor_id=1)
        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )

        worker_alias = await worker.resolve("alias")
        worker_alias["events"].append("worker")

        _apply_worker_update(parent, worker, snapshot)

        assert live_shared is live_alias
        assert live_shared["events"] == ["worker"]

    async def test_test_generator_teardown_mutates_parent_after_merge(self):
        @resource(scope=Scope.PROCESS)
        def events():
            return []

        @resource(scope=Scope.TEST)
        def case_state(events):
            state = {"events": events, "body": []}
            yield state
            events.append("teardown")

        parent = ResourceResolver(registry)
        forked = parent.fork_for_test()
        state = await forked.resolve("case_state")
        snapshot = forked.export_sync_snapshot(["case_state"], sync_actor_id=1)

        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        worker_state = await worker.resolve("case_state")
        worker_state["body"].append("worker")

        _apply_worker_update(forked, worker, snapshot)

        assert state["body"] == ["worker"]
        await forked.teardown_scope(Scope.TEST)
        assert await parent.resolve("events") == ["teardown"]

    async def test_slots_private_fields_and_runtime_ignores_round_trip(self):
        @resource(scope=Scope.PROCESS)
        def state():
            return SlotsState()

        parent = ResourceResolver(registry)
        live = await parent.resolve("state")
        snapshot = parent.export_sync_snapshot(["state"], sync_actor_id=1)

        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        worker_state = await worker.resolve("state")
        worker_state.count = 8
        worker_state._private = "worker"
        worker_state.ctx.set(11)

        _apply_worker_update(parent, worker, snapshot)

        assert live.count == 8
        assert live._private == "worker"
        assert live.ctx.get() == 11
        assert isinstance(live.lock, type(threading.Lock()))

    async def test_remote_merge_keeps_live_identity(self):
        @resource(scope=Scope.PROCESS)
        def holder():
            return {"items": [Box(1), Box(2)]}

        parent = ResourceResolver(registry)
        state = await parent.resolve("holder")
        items_before = state["items"]
        snapshot = parent.export_sync_snapshot(["holder"], sync_actor_id=1)

        worker = await ResourceResolver.hydrate_from_sync_snapshot(
            snapshot,
            registry,
        )
        worker_state = await worker.resolve("holder")
        worker_state["items"].append(Box(3))

        _apply_worker_update(parent, worker, snapshot)

        assert state["items"] is items_before
        assert [box.value for box in state["items"]] == [1, 2, 3]
