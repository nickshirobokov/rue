"""Tests for resource blueprint transfer helpers."""

import threading
from pathlib import Path

import pytest

from rue.resources import (
    ResourceResolver,
    Scope,
    registry,
    resource,
)
from rue.resources.models import ResourceBlueprint, TransferStrategy
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


# -----------------------------------------------------------
# Serialization helpers
# -----------------------------------------------------------


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


# -----------------------------------------------------------
# ResourceResolver.build_blueprint
# -----------------------------------------------------------


class TestBuildBlueprint:
    async def test_serializable_resource_tagged_serialize(self):
        @resource(scope=Scope.PROCESS)
        def config():
            return {"host": "localhost", "port": 8080}

        resolver = ResourceResolver(registry)
        await resolver.resolve("config")

        blueprint = resolver.build_blueprint(["config"])

        assert len(blueprint.entries) == 1
        entry = blueprint.entries[0]
        assert entry.strategy == TransferStrategy.SERIALIZE
        assert entry.serialized_value is not None
        assert len(blueprint.resolution_order) == 0

    async def test_non_serializable_resource_tagged_re_resolve(self):
        @resource(scope=Scope.PROCESS)
        def lock_res():
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("lock_res")

        blueprint = resolver.build_blueprint(["lock_res"])

        assert len(blueprint.entries) == 1
        entry = blueprint.entries[0]
        assert entry.strategy == TransferStrategy.RE_RESOLVE
        assert entry.serialized_value is None
        assert blueprint.resolution_order == (entry.identity,)

    async def test_mixed_dependency_chain(self):
        """A(serializable) -> B(non-serializable, depends on A).

        Blueprint should contain both, with only B in
        resolution_order.
        """

        @resource(scope=Scope.PROCESS)
        def base_config():
            return {"db": "postgres://localhost"}

        @resource(scope=Scope.PROCESS)
        def db_conn(base_config):
            _ = base_config
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("db_conn")

        blueprint = resolver.build_blueprint(["db_conn"])

        entry_map = {e.identity.name: e for e in blueprint.entries}
        assert len(entry_map) == 2

        assert entry_map["base_config"].strategy == TransferStrategy.SERIALIZE
        assert entry_map["db_conn"].strategy == TransferStrategy.RE_RESOLVE

        assert len(blueprint.resolution_order) == 1
        assert blueprint.resolution_order[0].name == "db_conn"

    async def test_dependencies_captured_correctly(self):
        @resource(scope=Scope.PROCESS)
        def dep_a():
            return "a"

        @resource(scope=Scope.PROCESS)
        def dep_b(dep_a):
            return f"b+{dep_a}"

        resolver = ResourceResolver(registry)
        await resolver.resolve("dep_b")

        blueprint = resolver.build_blueprint(["dep_b"])

        entry_map = {e.identity.name: e for e in blueprint.entries}
        dep_b_entry = entry_map["dep_b"]
        dep_names = [d.name for d in dep_b_entry.dependencies]
        assert "dep_a" in dep_names

    async def test_test_scope_excluded(self):
        @resource(scope=Scope.TEST)
        def per_test():
            return "ephemeral"

        @resource(scope=Scope.PROCESS)
        def shared():
            return "durable"

        resolver = ResourceResolver(registry)
        await resolver.resolve("shared")
        await resolver.resolve("per_test")

        blueprint = resolver.build_blueprint(
            ["shared", "per_test"]
        )

        names = {e.identity.name for e in blueprint.entries}
        assert "shared" in names
        assert "per_test" not in names

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

    async def test_empty_blueprint_for_unknown_names(self):
        resolver = ResourceResolver(registry)
        blueprint = resolver.build_blueprint(["nonexistent"])

        assert len(blueprint.entries) == 0
        assert len(blueprint.resolution_order) == 0

    async def test_transitive_dependencies_included(self):
        """A -> B -> C: requesting C should include A, B, C."""

        @resource(scope=Scope.PROCESS)
        def level_a():
            return "a"

        @resource(scope=Scope.PROCESS)
        def level_b(level_a):
            return f"b({level_a})"

        @resource(scope=Scope.PROCESS)
        def level_c(level_b):
            _ = level_b
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("level_c")

        blueprint = resolver.build_blueprint(["level_c"])

        names = {e.identity.name for e in blueprint.entries}
        assert names == {"level_a", "level_b", "level_c"}

    async def test_topological_order_respects_dependencies(self):
        """RE_RESOLVE entries appear after their dependencies."""

        @resource(scope=Scope.PROCESS)
        def top():
            return threading.Lock()

        @resource(scope=Scope.PROCESS)
        def bottom(top):
            _ = top
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("bottom")

        blueprint = resolver.build_blueprint(["bottom"])

        order_names = [i.name for i in blueprint.resolution_order]
        assert order_names.index("top") < order_names.index("bottom")


# -----------------------------------------------------------
# ResourceResolver.build_from_blueprint
# -----------------------------------------------------------


class TestBuildFromBlueprint:
    async def test_deserializes_serialize_entries(self):
        @resource(scope=Scope.PROCESS)
        def config():
            return {"key": "value"}

        resolver = ResourceResolver(registry)
        await resolver.resolve("config")

        blueprint = resolver.build_blueprint(["config"])

        worker = await ResourceResolver.build_from_blueprint(
            blueprint, registry
        )
        cache = worker.cached_identities
        values = list(cache.values())
        assert len(values) == 1
        assert values[0] == {"key": "value"}

    async def test_re_resolves_non_serializable(self):
        call_count = 0

        @resource(scope=Scope.PROCESS)
        def lock_factory():
            nonlocal call_count
            call_count += 1
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("lock_factory")
        assert call_count == 1

        blueprint = resolver.build_blueprint(["lock_factory"])
        worker = await ResourceResolver.build_from_blueprint(
            blueprint, registry
        )

        # Was re-resolved (called again)
        assert call_count == 2
        cache = worker.cached_identities
        assert any(k.name == "lock_factory" for k in cache)

    async def test_re_resolve_uses_deserialized_dependency(self):
        """B(non-serializable) depends on A(serializable).

        Worker should deserialize A and use it to re-resolve B.
        """
        received_config = None

        @resource(scope=Scope.PROCESS)
        def config():
            return {"db": "postgres"}

        @resource(scope=Scope.PROCESS)
        def connection(config):
            nonlocal received_config
            received_config = config
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("connection")

        blueprint = resolver.build_blueprint(["connection"])
        received_config = None

        await ResourceResolver.build_from_blueprint(blueprint, registry)

        assert received_config == {"db": "postgres"}

    async def test_worker_fork_for_test(self):
        @resource(scope=Scope.PROCESS)
        def shared():
            return "shared_value"

        resolver = ResourceResolver(registry)
        await resolver.resolve("shared")

        blueprint = resolver.build_blueprint(["shared"])
        worker = await ResourceResolver.build_from_blueprint(
            blueprint, registry
        )

        forked = worker.fork_for_test()
        cache = forked.cached_identities
        values = list(cache.values())
        assert "shared_value" in values


# -----------------------------------------------------------
# Full round-trip integration
# -----------------------------------------------------------


class TestRoundTrip:
    async def test_full_round_trip_mixed_resources(self):
        """End-to-end: register -> resolve -> build -> hydrate.

        Verifies that serializable values survive the round-trip
        and non-serializable values are re-resolved correctly.
        """

        @resource(scope=Scope.PROCESS)
        def app_config():
            return {"env": "test", "debug": True}

        @resource(scope=Scope.PROCESS)
        def file_lock(app_config):
            _ = app_config
            return threading.Lock()

        @resource(scope=Scope.MODULE)
        def module_val():
            return [1, 2, 3]

        # Resolve everything in "main process"
        main_resolver = ResourceResolver(registry)
        await main_resolver.resolve("file_lock")
        await main_resolver.resolve("module_val")

        blueprint = main_resolver.build_blueprint(
            ["file_lock", "module_val"]
        )

        # Hydrate in "worker process"
        worker = await ResourceResolver.build_from_blueprint(
            blueprint, registry
        )
        cache = worker.cached_identities
        names = {k.name for k in cache}

        assert "app_config" in names
        assert "file_lock" in names
        assert "module_val" in names

        # Serializable values match
        config_identity = next(
            k for k in cache if k.name == "app_config"
        )
        assert cache[config_identity] == {"env": "test", "debug": True}

        # Non-serializable values are valid instances
        lock_identity = next(
            k for k in cache if k.name == "file_lock"
        )
        assert isinstance(cache[lock_identity], type(threading.Lock()))


# -----------------------------------------------------------
# Edge cases
# -----------------------------------------------------------


class TestEdgeCases:
    async def test_generator_serializable_yield(self):
        """Generator with serializable yield → SERIALIZE.

        Teardown stays in main process.
        """
        teardown_ran = False

        @resource(scope=Scope.PROCESS)
        def gen_config():
            yield {"setting": True}
            nonlocal teardown_ran
            teardown_ran = True

        resolver = ResourceResolver(registry)
        await resolver.resolve("gen_config")

        blueprint = resolver.build_blueprint(["gen_config"])

        entry = blueprint.entries[0]
        assert entry.strategy == TransferStrategy.SERIALIZE

        # Worker gets the deserialized value, no teardown
        worker = await ResourceResolver.build_from_blueprint(
            blueprint, registry
        )
        await worker.teardown()
        assert not teardown_ran

        # Main process teardown still works
        await resolver.teardown()
        assert teardown_ran

    async def test_generator_non_serializable_yield(self):
        """Generator with non-serializable yield → RE_RESOLVE.

        Worker re-runs generator and manages teardown.
        """
        resolve_count = 0

        @resource(scope=Scope.PROCESS)
        def gen_lock():
            nonlocal resolve_count
            resolve_count += 1
            lock = threading.Lock()
            yield lock

        resolver = ResourceResolver(registry)
        await resolver.resolve("gen_lock")
        assert resolve_count == 1

        blueprint = resolver.build_blueprint(["gen_lock"])
        entry = blueprint.entries[0]
        assert entry.strategy == TransferStrategy.RE_RESOLVE

        await ResourceResolver.build_from_blueprint(blueprint, registry)
        assert resolve_count == 2

    async def test_empty_blueprint_hydration(self):
        """Empty blueprint → empty resolver."""
        blueprint = ResourceBlueprint(
            entries=(),
            resolution_order=(),
            request_path=None,
        )
        worker = await ResourceResolver.build_from_blueprint(
            blueprint, registry
        )
        assert len(worker.cached_identities) == 0

    async def test_all_serializable(self):
        """All resources serializable → no resolution_order."""

        @resource(scope=Scope.PROCESS)
        def a():
            return 1

        @resource(scope=Scope.PROCESS)
        def b(a):
            return a + 1

        resolver = ResourceResolver(registry)
        await resolver.resolve("b")

        blueprint = resolver.build_blueprint(["b"])

        assert all(
            e.strategy == TransferStrategy.SERIALIZE
            for e in blueprint.entries
        )
        assert len(blueprint.resolution_order) == 0

    async def test_all_non_serializable(self):
        """All resources non-serializable → all in resolution_order."""

        @resource(scope=Scope.PROCESS)
        def lock_a():
            return threading.Lock()

        @resource(scope=Scope.PROCESS)
        def lock_b(lock_a):
            _ = lock_a
            return threading.Lock()

        resolver = ResourceResolver(registry)
        await resolver.resolve("lock_b")

        blueprint = resolver.build_blueprint(["lock_b"])

        assert all(
            e.strategy == TransferStrategy.RE_RESOLVE
            for e in blueprint.entries
        )
        assert len(blueprint.resolution_order) == 2

        order_names = [i.name for i in blueprint.resolution_order]
        assert order_names.index("lock_a") < order_names.index(
            "lock_b"
        )

    async def test_module_scope_included_in_blueprint(self):
        @resource(scope=Scope.MODULE)
        def mod_res():
            return "module_value"

        resolver = ResourceResolver(registry)
        await resolver.resolve("mod_res")

        blueprint = resolver.build_blueprint(["mod_res"])

        assert len(blueprint.entries) == 1
        assert blueprint.entries[0].identity.scope == Scope.MODULE
