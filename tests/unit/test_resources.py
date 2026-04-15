"""Tests for rue.resources module."""

import asyncio
import builtins
from pathlib import Path
from textwrap import dedent

import pytest

from rue.context.runtime import (
    CURRENT_RESOURCE_CONSUMER,
    CURRENT_RESOURCE_PROVIDER,
    CURRENT_RESOURCE_RESOLVER,
    CURRENT_TEST,
    TestContext as Ctx,
    bind,
)
from rue.resources import (
    ResourceRegistry,
    ResourceResolver,
    Scope,
    registry,
    resource,
)
from rue.testing.models import TestDefinition
from tests.unit.factories import make_definition


def _make_item(
    name: str = "test_fn",
    suffix: str | None = None,
    case_id=None,
    module_path: Path | None = None,
) -> TestDefinition:
    """Create a minimal TestDefinition for testing."""
    return make_definition(name, module_path=module_path or Path("test.py"), suffix=suffix, case_id=case_id)


def _register_resource_source(
    path: Path,
    source: str,
    *,
    resource_decorator=resource,
) -> None:
    namespace = {"resource": resource_decorator, "Scope": Scope}
    exec(compile(dedent(source), str(path.resolve()), "exec"), namespace)


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the global registry before and after each test."""
    registry.reset()
    yield
    registry.reset()


class TestResourceDecorator:
    """Tests for the @resource decorator."""

    @pytest.mark.parametrize(
        ("name", "kind", "expected_flags"),
        [
            (
                "sync_resource",
                "sync",
                {
                    "is_async": False,
                    "is_generator": False,
                    "is_async_generator": False,
                },
            ),
            (
                "async_resource",
                "async",
                {
                    "is_async": True,
                    "is_generator": False,
                    "is_async_generator": False,
                },
            ),
        ],
    )
    def test_registers_callable_shape(
        self,
        name,
        kind,
        expected_flags,
    ):
        if kind == "sync":

            @resource
            def sync_resource():
                return "value"

        else:

            @resource
            async def async_resource():
                return "async_value"

        defn = registry.get(name)
        assert defn is not None
        assert defn.identity.name == name
        assert defn.identity.scope == Scope.CASE
        assert defn.is_async == expected_flags["is_async"]
        assert defn.is_generator == expected_flags["is_generator"]
        assert defn.is_async_generator == expected_flags["is_async_generator"]

    @pytest.mark.parametrize(
        ("name", "register", "expected_flags"),
        [
            (
                "gen_resource",
                "sync",
                {
                    "is_async": False,
                    "is_generator": True,
                    "is_async_generator": False,
                },
            ),
            (
                "async_gen_resource",
                "async",
                {
                    "is_async": True,
                    "is_generator": False,
                    "is_async_generator": True,
                },
            ),
        ],
    )
    def test_registers_generator_shape(
        self,
        name,
        register,
        expected_flags,
    ):
        if register == "sync":

            @resource
            def gen_resource():
                yield "gen_value"

        else:

            @resource
            async def async_gen_resource():
                yield "async_gen_value"

        defn = registry.get(name)
        assert defn is not None
        assert defn.is_async == expected_flags["is_async"]
        assert defn.is_generator == expected_flags["is_generator"]
        assert defn.is_async_generator == expected_flags["is_async_generator"]

    @pytest.mark.parametrize(
        ("scope_value", "expected_scope", "name"),
        [
            ("suite", Scope.SUITE, "suite_resource"),
            (Scope.SESSION, Scope.SESSION, "session_resource"),
        ],
    )
    def test_scope_normalization(self, scope_value, expected_scope, name):
        if expected_scope == Scope.SUITE:

            @resource(scope=scope_value)
            def suite_resource():
                return "suite"

        else:

            @resource(scope=scope_value)
            def session_resource():
                return "session"

        defn = registry.get(name)
        assert defn is not None
        assert defn.identity.scope == expected_scope

    def test_detects_dependencies(self):
        @resource
        def base():
            return 1

        @resource
        def dependent(base, other):
            return base + other

        defn = registry.get("dependent")
        assert defn is not None
        assert defn.dependencies == ["base", "other"]

    def test_ignores_self_and_cls_in_dependencies(self):
        @resource
        def dependent(self, cls, base, other):
            return base + other

        defn = registry.get("dependent")
        assert defn is not None
        assert defn.dependencies == ["base", "other"]


class TestResourceRegistry:
    def test_registers_definitions_and_session_index(self, tmp_path):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "root"
            """,
            resource_decorator=custom_registry.resource,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "child"
            """,
            resource_decorator=custom_registry.resource,
        )

        definition = custom_registry.get("shared")
        assert definition is not None
        assert definition.identity.scope == Scope.SESSION
        assert definition.identity.origin_dir == child.resolve()

    def test_select_picks_nearest_ancestor_session_definition(self, tmp_path):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        child = root / "tests" / "child"
        sibling = root / "tests" / "sibling"
        child.mkdir(parents=True)
        sibling.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "root"
            """,
            resource_decorator=custom_registry.resource,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "child"
            """,
            resource_decorator=custom_registry.resource,
        )

        child_selected = custom_registry.select(
            "shared", child / "rue_child.py"
        )
        sibling_selected = custom_registry.select(
            "shared",
            sibling / "rue_sibling.py",
        )

        assert child_selected.definition.identity.origin_dir == child.resolve()
        assert sibling_selected.definition.identity.origin_dir == root.resolve()

    def test_non_session_definition_wins_over_session_definition(
        self, tmp_path
    ):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        root.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "session"
            """,
            resource_decorator=custom_registry.resource,
        )

        @custom_registry.resource(scope=Scope.SUITE)
        def shared():
            return "suite"

        selected = custom_registry.select("shared", root / "rue_test.py")

        assert selected.definition.identity.scope == Scope.SUITE
        assert selected.definition.identity.name == "shared"
        assert selected.definition.identity.provider_dir is not None

    def test_reset_restores_builtin_resources(self):
        custom_registry = ResourceRegistry()

        @custom_registry.resource
        def builtin_resource():
            return "builtin"

        @custom_registry.resource(scope=Scope.SESSION)
        def builtin_session():
            return "builtin-session"

        custom_registry.mark_builtin("builtin_resource")
        custom_registry.mark_builtin("builtin_session")

        @custom_registry.resource
        def extra_resource():
            return "extra"

        @custom_registry.resource(scope=Scope.SESSION)
        def builtin_session():
            return "override"

        custom_registry.reset()

        builtin_resource_def = custom_registry.get("builtin_resource")
        builtin_session_def = custom_registry.get("builtin_session")
        extra_resource_def = custom_registry.get("extra_resource")

        assert builtin_resource_def is not None
        assert builtin_session_def is not None
        assert extra_resource_def is None
        assert builtin_session_def.fn() == "builtin-session"


class TestResourceResolver:
    """Tests for ResourceResolver."""

    def test_requires_explicit_registry(self):
        with pytest.raises(TypeError):
            ResourceResolver()  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        ("name", "kind", "expected"),
        [
            ("simple", "sync", 42),
            ("async_simple", "async", "async_result"),
        ],
    )
    @pytest.mark.asyncio
    async def test_resolves_registered_resource(
        self,
        name,
        kind,
        expected,
    ):
        if kind == "sync":

            @resource
            def simple():
                return 42

        else:

            @resource
            async def async_simple():
                return "async_result"

        resolver = ResourceResolver(registry)
        assert await resolver.resolve(name) == expected

    @pytest.mark.asyncio
    async def test_caches_case_scope(self):
        call_count = 0

        @resource(scope="case")
        def counted():
            nonlocal call_count
            call_count += 1
            return call_count

        resolver = ResourceResolver(registry)
        v1 = await resolver.resolve("counted")
        v2 = await resolver.resolve("counted")
        assert v1 == v2 == 1
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_resolves_dependencies(self):
        @resource
        def base_val():
            return 10

        @resource
        def derived(base_val):
            return base_val * 2

        resolver = ResourceResolver(registry)
        value = await resolver.resolve("derived")
        assert value == 20

    @pytest.mark.asyncio
    async def test_records_direct_dependency_graph(self):
        observed: list[list[str]] = []

        @resource
        def leaf():
            return "leaf"

        @resource
        def middle(leaf):
            provider = CURRENT_RESOURCE_PROVIDER.get()
            resolver = CURRENT_RESOURCE_RESOLVER.get()
            assert provider is not None
            assert resolver is not None
            observed.append(
                [
                    identity.name
                    for identity in resolver.direct_dependencies_for(
                        provider.identity
                    )
                ]
            )
            return leaf

        @resource
        def root(middle):
            provider = CURRENT_RESOURCE_PROVIDER.get()
            resolver = CURRENT_RESOURCE_RESOLVER.get()
            assert provider is not None
            assert resolver is not None
            observed.append(
                [
                    identity.name
                    for identity in resolver.direct_dependencies_for(
                        provider.identity
                    )
                ]
            )
            return middle

        resolver = ResourceResolver(registry)
        assert await resolver.resolve("root") == "leaf"
        assert observed == [["leaf"], ["middle"]]

    @pytest.mark.asyncio
    async def test_unknown_resource_raises(self):
        resolver = ResourceResolver(registry)
        with pytest.raises(ValueError, match="Unknown resource: unknown"):
            await resolver.resolve("unknown")

    @pytest.mark.asyncio
    async def test_resolve_many(self):
        @resource
        def res_a():
            return "a"

        @resource
        def res_b():
            return "b"

        resolver = ResourceResolver(registry)
        values = await resolver.resolve_many(["res_a", "res_b"])
        assert values == {"res_a": "a", "res_b": "b"}


class TestResourceTeardown:
    """Tests for resource teardown."""

    @pytest.mark.parametrize(
        ("name", "kind", "expected"),
        [
            ("gen_res", "sync", "value"),
            ("async_gen_res", "async", "async_value"),
        ],
    )
    @pytest.mark.asyncio
    async def test_generator_teardown_runs(
        self,
        name,
        kind,
        expected,
    ):
        teardown_called = False

        if kind == "sync":

            @resource
            def gen_res():
                yield "value"
                nonlocal teardown_called
                teardown_called = True

        else:

            @resource
            async def async_gen_res():
                yield "async_value"
                nonlocal teardown_called
                teardown_called = True

        resolver = ResourceResolver(registry)
        assert await resolver.resolve(name) == expected

        await resolver.teardown()
        assert teardown_called

    @pytest.mark.asyncio
    async def test_teardown_scope_case(self):
        case_torn = False
        suite_torn = False

        @resource(scope="case")
        def case_res():
            yield "case"
            nonlocal case_torn
            case_torn = True

        @resource(scope="suite")
        def suite_res():
            yield "suite"
            nonlocal suite_torn
            suite_torn = True

        resolver = ResourceResolver(registry)
        await resolver.resolve("case_res")
        await resolver.resolve("suite_res")

        await resolver.teardown_scope(Scope.CASE)
        assert case_torn
        assert not suite_torn

        await resolver.teardown()
        assert suite_torn

    @pytest.mark.asyncio
    async def test_teardown_clears_cache(self):
        call_count = 0

        @resource(scope="case")
        def counted_case():
            nonlocal call_count
            call_count += 1
            return call_count

        resolver = ResourceResolver(registry)
        v1 = await resolver.resolve("counted_case")
        assert v1 == 1

        await resolver.teardown_scope(Scope.CASE)

        v2 = await resolver.resolve("counted_case")
        assert v2 == 2


class TestForkForCase:
    """Tests for fork_for_case and parent/child isolation."""

    @pytest.mark.asyncio
    async def test_child_case_scope_isolated(self):
        call_count = 0

        @resource(scope="case")
        def case_val():
            nonlocal call_count
            call_count += 1
            return call_count

        parent = ResourceResolver(registry)
        parent_val = await parent.resolve("case_val")
        assert parent_val == 1

        child = parent.fork_for_case()
        child_val = await child.resolve("case_val")
        assert child_val == 2  # New instance for child

    @pytest.mark.parametrize(
        ("scope", "name"),
        [
            (Scope.SUITE, "shared_suite"),
            (Scope.SESSION, "shared_session"),
        ],
    )
    @pytest.mark.asyncio
    async def test_shared_scopes_resolve_once_across_children(
        self,
        scope,
        name,
    ):
        create_count = 0
        teardown_count = 0

        if scope == Scope.SUITE:

            @resource(scope=scope)
            async def shared_suite():
                nonlocal create_count, teardown_count
                create_count += 1
                await asyncio.sleep(0.02)
                yield f"{scope.value}_{create_count}"
                teardown_count += 1

        else:

            @resource(scope=scope)
            async def shared_session():
                nonlocal create_count, teardown_count
                create_count += 1
                await asyncio.sleep(0.02)
                yield f"{scope.value}_{create_count}"
                teardown_count += 1

        parent = ResourceResolver(registry)
        children = [parent.fork_for_case() for _ in range(8)]
        values = await asyncio.gather(
            *[child.resolve(name) for child in children]
        )

        assert values == [f"{scope.value}_1"] * len(children)
        assert create_count == 1

        await parent.teardown()
        assert teardown_count == 1


class TestHierarchicalSessionResources:
    """Tests for conftest-style SESSION resource lookup."""

    @pytest.mark.asyncio
    async def test_nearest_ancestor_session_resource_wins(self, tmp_path):
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "root"
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "child"
            """,
        )

        resolver = ResourceResolver(registry)

        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=root / "tests" / "rue_root.py")),
        ):
            assert await resolver.resolve("shared") == "root"

        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=child / "rue_child.py")),
        ):
            assert await resolver.resolve("shared") == "child"

    @pytest.mark.asyncio
    async def test_sibling_branch_uses_nearest_shared_ancestor(self, tmp_path):
        root = tmp_path / "project"
        branch = root / "tests" / "branch"
        sibling = root / "tests" / "sibling"
        branch.mkdir(parents=True)
        sibling.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "root"
            """,
        )
        _register_resource_source(
            branch / "confrue_branch.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "branch"
            """,
        )

        resolver = ResourceResolver(registry)
        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=sibling / "rue_sibling.py")),
        ):
            assert await resolver.resolve("shared") == "root"

    @pytest.mark.asyncio
    async def test_parent_session_dependency_uses_requesting_test_chain(
        self,
        tmp_path,
    ):
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "root"

            @resource(scope=Scope.SESSION)
            def consumer(shared):
                return f"consumer:{shared}"
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "child"
            """,
        )

        resolver = ResourceResolver(registry)
        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=child / "rue_child.py")),
        ):
            assert await resolver.resolve("consumer") == "consumer:child"

    @pytest.mark.asyncio
    async def test_direct_resolve_without_current_test_uses_flat_fallback(
        self,
        tmp_path,
    ):
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "root"
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.SESSION)
            def shared():
                return "child"
            """,
        )

        resolver = ResourceResolver(registry)
        assert await resolver.resolve("shared") == "child"

    @pytest.mark.asyncio
    async def test_hierarchical_session_resources_use_distinct_cache_keys(
        self,
        tmp_path,
        monkeypatch,
    ):
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)
        monkeypatch.setattr(builtins, "session_events", [], raising=False)

        _register_resource_source(
            root / "confrue_root.py",
            """
            import builtins

            @resource(scope=Scope.SESSION)
            def shared():
                builtins.session_events.append("root_create")
                yield "root"
                builtins.session_events.append("root_teardown")
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            import builtins

            @resource(scope=Scope.SESSION)
            def shared():
                builtins.session_events.append("child_create")
                yield "child"
                builtins.session_events.append("child_teardown")
            """,
        )

        resolver = ResourceResolver(registry)

        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=root / "tests" / "rue_root.py")),
        ):
            assert await resolver.resolve("shared") == "root"

        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=child / "rue_child.py")),
        ):
            assert await resolver.resolve("shared") == "child"

        with bind(
            CURRENT_TEST,
            Ctx(item=_make_item(module_path=root / "tests" / "rue_root.py")),
        ):
            assert await resolver.resolve("shared") == "root"

        cache_keys = [
            key
            for key in resolver._cache
            if key.scope == Scope.SESSION and key.name == "shared"
        ]
        assert len(cache_keys) == 2
        assert {key.provider_dir for key in cache_keys} == {
            str(root.resolve()),
            str(child.resolve()),
        }

        await resolver.teardown()
        assert builtins.session_events == [
            "root_create",
            "child_create",
            "child_teardown",
            "root_teardown",
        ]


class TestResourceHooks:
    """Tests for on_resolve, on_injection and on_teardown hooks."""

    @pytest.mark.asyncio
    async def test_on_injection_transforms_value(self):
        @resource(on_injection=lambda v: v * 2)
        def doubled():
            return 10

        resolver = ResourceResolver(registry)
        value = await resolver.resolve("doubled")

        assert value == 20

    @pytest.mark.asyncio
    async def test_on_resolve_called_once(self):
        resolve_calls = []

        def track_resolve(value):
            resolve_calls.append(value)
            return value

        @resource(on_resolve=track_resolve)
        def simple():
            return 42

        resolver = ResourceResolver(registry)
        await resolver.resolve("simple")
        await resolver.resolve("simple")

        assert resolve_calls == [42]

    @pytest.mark.asyncio
    async def test_on_teardown_called_after_generator_teardown(self):
        call_order = []

        def on_teardown_hook(value):
            call_order.append(("hook", value))

        @resource(on_teardown=on_teardown_hook)
        def gen_res():
            yield "value"
            call_order.append(("generator_teardown",))

        resolver = ResourceResolver(registry)
        await resolver.resolve("gen_res")
        await resolver.teardown()

        assert call_order == [("generator_teardown",), ("hook", "value")]

    @pytest.mark.asyncio
    async def test_on_teardown_with_teardown_scope(self):
        teardown_hook_called = False

        def on_teardown_hook(value):
            nonlocal teardown_hook_called
            teardown_hook_called = True

        @resource(scope="case", on_teardown=on_teardown_hook)
        def case_gen():
            yield "case_value"

        resolver = ResourceResolver(registry)
        await resolver.resolve("case_gen")

        assert not teardown_hook_called
        await resolver.teardown_scope(Scope.CASE)
        assert teardown_hook_called

    @pytest.mark.asyncio
    async def test_hooks_with_async_generator(self):
        injection_value = None
        teardown_value = None

        def on_injection_hook(value):
            nonlocal injection_value
            injection_value = value
            return value

        def on_teardown_hook(value):
            nonlocal teardown_value
            teardown_value = value

        @resource(on_injection=on_injection_hook, on_teardown=on_teardown_hook)
        async def async_gen():
            yield "async_value"

        resolver = ResourceResolver(registry)
        value = await resolver.resolve("async_gen")

        assert value == "async_value"
        assert injection_value == "async_value"

        await resolver.teardown()
        assert teardown_value == "async_value"

    @pytest.mark.asyncio
    async def test_on_injection_receives_custom_context(self):
        received_name = None

        def hook(value):
            nonlocal received_name
            if test_ctx := CURRENT_TEST.get():
                received_name = test_ctx.item.name
            else:
                received_name = "unknown"
            return value

        @resource(on_injection=hook)
        def simple():
            return 42

        resolver = ResourceResolver(registry)
        with bind(CURRENT_TEST, Ctx(item=_make_item("my_test"))):
            await resolver.resolve("simple")
        assert received_name == "my_test"

    @pytest.mark.asyncio
    async def test_nested_dependency_context(self):
        history = []

        def hook(value):
            if consumer_name := CURRENT_RESOURCE_CONSUMER.get():
                history.append((consumer_name, value))
            else:
                history.append(("unknown", value))
            return value

        @resource(on_injection=hook)
        def leaf():
            return "leaf"

        @resource(on_injection=hook)
        def middle(leaf):
            return f"middle({leaf})"

        @resource
        def top(middle):
            return f"top({middle})"

        resolver = ResourceResolver(registry)
        await resolver.resolve("top")

        assert history == [
            ("middle", "leaf"),
            ("top", "middle(leaf)"),
        ]

    @pytest.mark.asyncio
    async def test_on_injection_called_for_cached_resource(self):
        call_count = 0

        def hook(value):
            nonlocal call_count
            call_count += 1
            return value

        @resource(on_injection=hook)
        def cached_res():
            return "val"

        resolver = ResourceResolver(registry)
        await resolver.resolve("cached_res")
        await resolver.resolve("cached_res")

        # Hook called twice, once for each injection
        assert call_count == 2


class TestResourceResolutionErrors:
    """Tests to ensure resource resolution errors are properly surfaced."""

    @pytest.mark.asyncio
    async def test_circular_suite_dependency_raises_error(self):
        @resource(scope="suite")
        async def shared_left(shared_right):
            return shared_right

        @resource(scope="suite")
        async def shared_right(shared_left):
            return shared_left

        resolver = ResourceResolver(registry)
        with pytest.raises(
            RuntimeError, match="Circular resource dependency detected"
        ):
            await asyncio.wait_for(resolver.resolve("shared_left"), timeout=0.2)

    @pytest.mark.asyncio
    async def test_resource_on_injection_error(self):
        """Test that errors in on_injection hook are surfaced."""

        def raise_on_injection(value):
            raise RuntimeError("on_injection hook failed")

        @resource(on_injection=raise_on_injection)
        def resource_with_injection():
            return "value"

        resolver = ResourceResolver(registry)
        with pytest.raises(RuntimeError, match="on_injection hook failed"):
            await resolver.resolve("resource_with_injection")

    @pytest.mark.asyncio
    async def test_teardown_errors_are_aggregated(self):
        def raise_on_teardown(_value):
            raise RuntimeError("hook teardown failed")

        @resource(scope=Scope.CASE, on_teardown=raise_on_teardown)
        def resource_with_teardown_errors():
            yield "value"
            raise RuntimeError("generator teardown failed")

        resolver = ResourceResolver(registry)
        assert (
            await resolver.resolve("resource_with_teardown_errors") == "value"
        )

        with pytest.raises(ExceptionGroup) as exc_info:
            await resolver.teardown_scope(Scope.CASE)

        messages = {str(error) for error in exc_info.value.exceptions}
        assert any(
            "generator teardown failed" in message for message in messages
        )
        assert any("hook teardown failed" in message for message in messages)
