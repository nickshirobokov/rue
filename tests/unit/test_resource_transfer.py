"""Tests for snapshot-based resource transfer helpers."""

from __future__ import annotations

import threading
from contextvars import ContextVar
from pathlib import Path

import pytest
from deepdiff import DeepDiff, Delta

from rue.resources import ResourceResolver, Scope, registry, resource
from rue.resources.models import ResourceBlueprint
from rue.resources.serialization import (
    check_serializable,
    deserialize_value,
    serialize_value,
)


@pytest.fixture(autouse=True)
def clean_registry():
    registry.reset()
    yield
    registry.reset()


class SlotsState:
    __slots__ = ("count", "_private", "_cache", "lock", "ctx")

    def __init__(self) -> None:
        self.count = 1
        self._private = "secret"
        self._cache = {"skip": True}
        self.lock = threading.Lock()
        self.ctx = ContextVar("slots_state_ctx", default=0)
        self.ctx.set(5)


def _merge_payloads(
    resolver: ResourceResolver,
    base: ResourceBlueprint,
    current: ResourceBlueprint,
    worker: ResourceBlueprint,
) -> dict[str, object]:
    base_payload = resolver.snapshot_payload(base)
    parent_diff = DeepDiff(
        base_payload,
        resolver.snapshot_payload(current),
        verbose_level=2,
    )
    worker_diff = DeepDiff(
        base_payload,
        resolver.snapshot_payload(worker),
        verbose_level=2,
    )
    merged = base_payload + Delta(parent_diff)
    return merged + Delta(worker_diff)


class TestCheckSerializable:
    def test_primitive_types_are_serializable(self):
        assert check_serializable(42)
        assert check_serializable("hello")
        assert check_serializable([1, 2, 3])
        assert check_serializable({"key": "value"})

    def test_non_serializable_objects(self):
        lock = threading.Lock()
        assert not check_serializable(lock)


class TestSerializeRoundTrip:
    def test_round_trip_primitive(self):
        original = {"a": 1, "b": [2, 3]}
        data = serialize_value(original)
        restored = deserialize_value(data)
        assert restored == original

    def test_round_trip_nested(self):
        original = {"nested": {"deep": [1, 2, 3]}}
        data = serialize_value(original)
        restored = deserialize_value(data)
        assert restored == original


class TestBuildBlueprint:
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

        blueprint = resolver.build_blueprint(["shared", "per_test"])

        names = {identity.name for identity in blueprint.res_specs}
        assert names == {"shared", "per_test"}
        assert set(blueprint.root_ids) == {
            identity.snapshot_key for identity in blueprint.res_specs
        }

    async def test_records_ignored_runtime_fields(self):
        @resource(scope=Scope.PROCESS)
        def state():
            return SlotsState()

        resolver = ResourceResolver(registry)
        await resolver.resolve("state")

        blueprint = resolver.build_blueprint(["state"])
        identity = blueprint.res_specs[0]
        root_node = blueprint.nodes[blueprint.root_ids[identity.snapshot_key]]
        attrs = set(root_node["attrs"])

        assert "count" in attrs
        assert "_private" in attrs
        assert "_cache" not in attrs
        assert "lock" not in attrs
        assert blueprint.ignored_paths[identity.snapshot_key] == [
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

        blueprint = resolver.build_blueprint(["alias"])
        identity_map = {identity.name: identity for identity in blueprint.res_specs}

        assert (
            blueprint.root_ids[identity_map["shared"].snapshot_key]
            == blueprint.root_ids[identity_map["alias"].snapshot_key]
        )

    async def test_request_path_stored(self):
        @resource(scope=Scope.PROCESS)
        def simple():
            return 1

        resolver = ResourceResolver(registry)
        await resolver.resolve("simple")

        blueprint = resolver.build_blueprint(
            ["simple"],
            request_path=Path("/project/tests/test_foo.py"),
        )

        assert blueprint.request_path == "/project/tests/test_foo.py"

    def test_build_blueprint_requires_cached_resources(self):
        resolver = ResourceResolver(registry)
        with pytest.raises(ValueError, match="nonexistent"):
            resolver.build_blueprint(["nonexistent"])


class TestBuildFromBlueprint:
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

        blueprint = resolver.build_blueprint(["config"])
        worker = await ResourceResolver.build_from_blueprint(
            blueprint,
            registry,
        )

        assert resolve_count == 2
        assert await worker.resolve("config") == {"key": "value"}

    async def test_worker_applies_parent_state_over_shadow_defaults(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"count": 0}

        resolver = ResourceResolver(registry)
        shared = await resolver.resolve("shared")
        shared["count"] = 4

        blueprint = resolver.build_blueprint(["shared"])
        worker = await ResourceResolver.build_from_blueprint(
            blueprint,
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

        blueprint = resolver.build_blueprint(["holder"])
        worker = await ResourceResolver.build_from_blueprint(
            blueprint,
            registry,
        )
        hydrated = await worker.resolve("holder")

        assert hydrated.ctx.get() == 7

    async def test_empty_blueprint_hydration(self):
        blueprint = ResourceBlueprint(
            res_specs=(),
            request_path=None,
        )
        worker = await ResourceResolver.build_from_blueprint(
            blueprint,
            registry,
        )

        assert len(worker.cached_identities) == 0


class TestRoundTrip:
    async def test_parent_and_worker_diffs_use_worker_last_on_conflict(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return {"values": ["base"]}

        resolver = ResourceResolver(registry)
        shared = await resolver.resolve("shared")
        base = resolver.build_blueprint(["shared"])

        worker = await ResourceResolver.build_from_blueprint(base, registry)
        worker_shared = await worker.resolve("shared")

        shared["values"].append("parent")
        worker_shared["values"].append("worker")

        current = resolver.snapshot_blueprint(
            base.res_specs,
            request_path=Path("/tmp/test_shared.py"),
        )
        worker_snapshot = worker.snapshot_blueprint(
            base.res_specs,
            request_path=Path("/tmp/test_shared.py"),
        )

        resolver.apply_snapshot(
            _merge_payloads(resolver, base, current, worker_snapshot)
        )

        assert shared["values"] == ["base", "worker"]

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
        base = forked.build_blueprint(["case_state"])

        worker = await ResourceResolver.build_from_blueprint(base, registry)
        worker_state = await worker.resolve("case_state")
        worker_state["body"].append("worker")

        current = forked.snapshot_blueprint(
            base.res_specs,
            request_path=Path("/tmp/test_case.py"),
        )
        worker_snapshot = worker.snapshot_blueprint(
            base.res_specs,
            request_path=Path("/tmp/test_case.py"),
        )
        forked.apply_snapshot(
            _merge_payloads(forked, base, current, worker_snapshot)
        )

        assert state["body"] == ["worker"]
        await forked.teardown_scope(Scope.TEST)
        assert await parent.resolve("events") == ["teardown"]

    async def test_slots_private_fields_and_runtime_ignores_round_trip(self):
        @resource(scope=Scope.PROCESS)
        def state():
            return SlotsState()

        parent = ResourceResolver(registry)
        live = await parent.resolve("state")
        base = parent.build_blueprint(["state"])

        worker = await ResourceResolver.build_from_blueprint(base, registry)
        worker_state = await worker.resolve("state")
        worker_state.count = 8
        worker_state._private = "worker"
        worker_state.ctx.set(11)

        current = parent.snapshot_blueprint(
            base.res_specs,
            request_path=Path("/tmp/test_slots.py"),
        )
        worker_snapshot = worker.snapshot_blueprint(
            base.res_specs,
            request_path=Path("/tmp/test_slots.py"),
        )
        parent.apply_snapshot(
            _merge_payloads(parent, base, current, worker_snapshot)
        )

        assert live.count == 8
        assert live._private == "worker"
        assert live.ctx.get() == 11
        assert isinstance(live.lock, type(threading.Lock()))
