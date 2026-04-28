"""Tests for rue.resources module."""

import asyncio
import builtins
from pathlib import Path
from textwrap import dedent

import pytest

from rue.context.runtime import (
    CURRENT_RESOURCE_TRANSACTION,
)
from rue.resources import (
    ResourceRegistry,
    ResourceResolver,
    Scope,
    registry,
    resource,
)
from rue.testing.models import LoadedTestDef
from tests.unit.factories import make_definition


def _make_item(
    name: str = "test_fn",
    suffix: str | None = None,
    case_id=None,
    module_path: Path | None = None,
) -> LoadedTestDef:
    """Create a minimal LoadedTestDef for testing."""
    return make_definition(
        name,
        module_path=module_path or Path("test.py"),
        suffix=suffix,
        case_id=case_id,
    )


def _consumer_spec(
    name: str = "test_fn",
    *,
    module_path: Path | None = None,
):
    return _make_item(name=name, module_path=module_path).spec


def _resource_graph(
    resource_registry: ResourceRegistry,
    resource_names: tuple[str, ...],
    *,
    consumer_spec=None,
    key: str = "test",
):
    consumer = consumer_spec or _consumer_spec()
    return resource_registry.compile_graph({key: (consumer, resource_names)})


async def _resolve(
    resolver: ResourceResolver,
    name: str,
    *,
    consumer_spec=None,
):
    consumer = consumer_spec or _consumer_spec()
    graph = _resource_graph(
        resolver.registry,
        (name,),
        consumer_spec=consumer,
    )
    return await resolver.resolve_resource(
        graph.injections_by_key["test"][name],
        consumer_spec=consumer,
    )


def _register_resource_source(
    path: Path,
    source: str,
    *,
    resource_decorator=resource,
) -> None:
    namespace = {"resource": resource_decorator, "Scope": Scope}
    exec(compile(dedent(source), str(path.resolve()), "exec"), namespace)


def _only_definition(
    resource_registry,
    name: str,
    scope: Scope = Scope.TEST,
):
    by_path = resource_registry._definitions[name][scope]
    return next(reversed(by_path.values()))


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

        defn = _only_definition(registry, name)
        assert defn.spec.name == name
        assert defn.spec.scope == Scope.TEST
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

        defn = _only_definition(registry, name)
        assert defn.is_async == expected_flags["is_async"]
        assert defn.is_generator == expected_flags["is_generator"]
        assert defn.is_async_generator == expected_flags["is_async_generator"]

    @pytest.mark.parametrize(
        ("scope_value", "expected_scope", "name"),
        [
            ("module", Scope.MODULE, "suite_resource"),
            (Scope.RUN, Scope.RUN, "session_resource"),
        ],
    )
    def test_scope_normalization(self, scope_value, expected_scope, name):
        if expected_scope == Scope.MODULE:

            @resource(scope=scope_value)
            def suite_resource():
                return "module"

        else:

            @resource(scope=scope_value)
            def session_resource():
                return "run"

        defn = _only_definition(registry, name, expected_scope)
        assert defn.spec.scope == expected_scope

    def test_detects_dependencies(self):
        @resource
        def base():
            return 1

        @resource
        def dependent(base, other):
            return base + other

        defn = _only_definition(registry, "dependent")
        assert defn.spec.dependencies == ("base", "other")

    def test_ignores_self_and_cls_in_dependencies(self):
        @resource
        def dependent(self, cls, base, other):
            return base + other

        defn = _only_definition(registry, "dependent")
        assert defn.spec.dependencies == ("base", "other")


class TestResourceRegistry:
    def test_compile_graph_single_resource(self):
        @resource
        def leaf():
            return "leaf"

        graph = _resource_graph(registry, ("leaf",))

        root_names = [identity.name for identity in graph.roots_by_key["test"]]
        node_names = [identity.name for identity in graph.order_by_key["test"]]
        assert root_names == ["leaf"]
        assert node_names == ["leaf"]
        assert graph.dependencies_by_spec[graph.roots_by_key["test"][0]] == ()

    def test_compile_graph_transitive_dependency_first(self):
        @resource
        def leaf():
            return "leaf"

        @resource
        def middle(leaf):
            return leaf

        @resource
        def root(middle):
            return middle

        graph = _resource_graph(registry, ("root",))
        nodes = graph.order_by_key["test"]

        node_names = [identity.name for identity in nodes]
        assert node_names == ["leaf", "middle", "root"]
        assert graph.dependencies_by_spec[nodes[2]] == (nodes[1],)
        assert graph.dependencies_by_spec[nodes[1]] == (nodes[0],)

    def test_compile_graph_shares_dependency_spec(self):
        @resource
        def shared():
            return "shared"

        @resource
        def left(shared):
            return shared

        @resource
        def right(shared):
            return shared

        @resource
        def root(left, right):
            return left, right

        graph = _resource_graph(registry, ("root",))
        root_spec = graph.roots_by_key["test"][0]
        left_spec, right_spec = graph.dependencies_by_spec[root_spec]

        assert (
            graph.dependencies_by_spec[left_spec][0]
            == graph.dependencies_by_spec[right_spec][0]
        )
        node_names = [identity.name for identity in graph.order_by_key["test"]]
        assert node_names == ["shared", "left", "right", "root"]

    def test_compile_graph_preserves_root_order(self):
        @resource
        def left():
            return "left"

        @resource
        def right():
            return "right"

        graph = _resource_graph(registry, ("right", "left"))

        root_names = [identity.name for identity in graph.roots_by_key["test"]]
        assert root_names == ["right", "left"]

    def test_compile_graph_keeps_same_name_run_roots(
        self, tmp_path
    ):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        child = root / "tests" / "child"
        sibling = root / "tests" / "sibling"
        child.mkdir(parents=True)
        sibling.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "root"
            """,
            resource_decorator=custom_registry.resource,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "child"
            """,
            resource_decorator=custom_registry.resource,
        )

        graph = custom_registry.compile_graph(
            {
                "child": (
                    _consumer_spec(module_path=child / "rue_child.py"),
                    ("shared",),
                ),
                "sibling": (
                    _consumer_spec(module_path=sibling / "rue_sibling.py"),
                    ("shared",),
                ),
            }
        )

        assert {
            graph.roots_by_key[key][0].module_path.parent
            for key in ("child", "sibling")
        } == {child.resolve(), root.resolve()}

    def test_run_scope_keeps_directory_overrides(self, tmp_path):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "root"
            """,
            resource_decorator=custom_registry.resource,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "child"
            """,
            resource_decorator=custom_registry.resource,
        )

        root_selected = _only_definition(
            custom_registry,
            "shared",
            Scope.RUN,
        )
        root_graph = _resource_graph(
            custom_registry,
            ("shared",),
            consumer_spec=_consumer_spec(module_path=root / "rue_root.py"),
        )
        child_selected = _only_definition(
            custom_registry,
            "shared",
            Scope.RUN,
        )
        child_graph = _resource_graph(
            custom_registry,
            ("shared",),
            consumer_spec=_consumer_spec(module_path=child / "rue_child.py"),
        )

        assert {
            root_graph.injections_by_key["test"]["shared"].module_path.parent,
            child_graph.injections_by_key["test"]["shared"].module_path.parent,
        } == {root.resolve(), child.resolve()}
        assert root_selected.spec.scope == Scope.RUN
        assert child_selected.spec.scope == Scope.RUN

    def test_select_picks_nearest_ancestor_process_definition(self, tmp_path):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        child = root / "tests" / "child"
        sibling = root / "tests" / "sibling"
        child.mkdir(parents=True)
        sibling.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "root"
            """,
            resource_decorator=custom_registry.resource,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "child"
            """,
            resource_decorator=custom_registry.resource,
        )

        child_graph = _resource_graph(
            custom_registry,
            ("shared",),
            consumer_spec=_consumer_spec(module_path=child / "rue_child.py"),
        )
        sibling_graph = _resource_graph(
            custom_registry,
            ("shared",),
            consumer_spec=_consumer_spec(
                module_path=sibling / "rue_sibling.py"
            ),
        )

        assert (
            child_graph.injections_by_key["test"][
                "shared"
            ].module_path.parent
            == child.resolve()
        )
        assert (
            sibling_graph.injections_by_key["test"][
                "shared"
            ].module_path.parent
            == root.resolve()
        )

    def test_non_process_definition_wins_over_process_definition(
        self, tmp_path
    ):
        custom_registry = ResourceRegistry()
        root = tmp_path / "project"
        root.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "run"
            """,
            resource_decorator=custom_registry.resource,
        )

        @custom_registry.resource(scope=Scope.MODULE)
        def shared():
            return "module"

        graph = _resource_graph(
            custom_registry,
            ("shared",),
            consumer_spec=_consumer_spec(module_path=root / "rue_test.py"),
        )
        selected = custom_registry.definition(
            graph.injections_by_key["test"]["shared"]
        )

        assert selected.spec.scope == Scope.MODULE
        assert selected.spec.name == "shared"
        assert selected.spec.module_path is not None

    def test_reset_restores_builtin_resources(self):
        custom_registry = ResourceRegistry()

        @custom_registry.resource(builtin=True)
        def builtin_resource():
            return "builtin"

        @custom_registry.resource(scope=Scope.RUN, builtin=True)
        def builtin_session():
            return "builtin-session"

        @custom_registry.resource
        def extra_resource():
            return "extra"

        def builtin_session_override():
            return "override"

        builtin_session_override.__name__ = "builtin_session"
        custom_registry.resource(
            builtin_session_override,
            scope=Scope.RUN,
        )

        custom_registry.reset()

        builtin_resource_def = _only_definition(
            custom_registry,
            "builtin_resource",
        )
        builtin_session_def = _only_definition(
            custom_registry,
            "builtin_session",
            Scope.RUN,
        )

        assert builtin_resource_def is not None
        assert builtin_session_def is not None
        assert builtin_session_def.fn() == "builtin-session"
        with pytest.raises(ValueError, match="Unknown resource"):
            custom_registry.compile_graph(
                {"test": (_consumer_spec(), ("extra_resource",))}
            )


class TestResourceResolver:
    """Tests for ResourceResolver."""

    def test_requires_explicit_registry(self):
        with pytest.raises(TypeError):
            ResourceResolver()  # type: ignore[call-arg]

    @pytest.mark.asyncio
    async def test_resolve_requires_compiled_graph(self):
        @resource
        def simple():
            return 42

        resolver = ResourceResolver(registry)
        identity = _only_definition(registry, "simple").spec
        with pytest.raises(
            RuntimeError,
            match="Resource graph is not compiled",
        ):
            await resolver.resolve_resource(
                identity,
                consumer_spec=_consumer_spec(),
            )

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
        assert (
            await _resolve(resolver, name, consumer_spec=_consumer_spec())
            == expected
        )

    @pytest.mark.asyncio
    async def test_caches_test_scope(self):
        call_count = 0

        @resource(scope="test")
        def counted():
            nonlocal call_count
            call_count += 1
            return call_count

        resolver = ResourceResolver(registry)
        v1 = await _resolve(resolver, "counted", consumer_spec=_consumer_spec())
        v2 = await _resolve(resolver, "counted", consumer_spec=_consumer_spec())
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
        value = await _resolve(
            resolver,
            "derived",
            consumer_spec=_consumer_spec(),
        )
        assert value == 20

    @pytest.mark.asyncio
    async def test_records_direct_dependency_graph(self):
        observed: list[list[str]] = []

        @resource
        def leaf():
            return "leaf"

        @resource
        def middle(leaf):
            transaction = CURRENT_RESOURCE_TRANSACTION.get()
            observed.append(
                [
                    identity.name
                    for identity in transaction.direct_dependencies
                ]
            )
            return leaf

        @resource
        def root(middle):
            transaction = CURRENT_RESOURCE_TRANSACTION.get()
            observed.append(
                [
                    identity.name
                    for identity in transaction.direct_dependencies
                ]
            )
            return middle

        resolver = ResourceResolver(registry)
        assert (
            await _resolve(resolver, "root", consumer_spec=_consumer_spec())
            == "leaf"
        )
        assert observed == [["leaf"], ["middle"]]

    @pytest.mark.asyncio
    async def test_unknown_resource_raises(self):
        resolver = ResourceResolver(registry)
        with pytest.raises(ValueError, match="Unknown resource: unknown"):
            await _resolve(resolver, "unknown", consumer_spec=_consumer_spec())


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
        assert (
            await _resolve(resolver, name, consumer_spec=_consumer_spec())
            == expected
        )

        await resolver.teardown()
        assert teardown_called

    @pytest.mark.asyncio
    async def test_teardown_scope_test(self):
        case_torn = False
        suite_torn = False

        @resource(scope="test")
        def case_res():
            yield "case"
            nonlocal case_torn
            case_torn = True

        @resource(scope="module")
        def suite_res():
            yield "suite"
            nonlocal suite_torn
            suite_torn = True

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "case_res", consumer_spec=_consumer_spec())
        await _resolve(resolver, "suite_res", consumer_spec=_consumer_spec())

        await resolver.teardown_scope(Scope.TEST)
        assert case_torn
        assert not suite_torn

        await resolver.teardown()
        assert suite_torn

    @pytest.mark.asyncio
    async def test_teardown_clears_cache(self):
        call_count = 0

        @resource(scope="test")
        def counted_case():
            nonlocal call_count
            call_count += 1
            return call_count

        resolver = ResourceResolver(registry)
        v1 = await _resolve(
            resolver,
            "counted_case",
            consumer_spec=_consumer_spec(),
        )
        assert v1 == 1

        await resolver.teardown_scope(Scope.TEST)

        v2 = await _resolve(
            resolver,
            "counted_case",
            consumer_spec=_consumer_spec(),
        )
        assert v2 == 2


class TestForkForTest:
    """Tests for fork_for_test and parent/child isolation."""

    @pytest.mark.asyncio
    async def test_child_test_scope_isolated(self):
        call_count = 0

        @resource(scope="test")
        def case_val():
            nonlocal call_count
            call_count += 1
            return call_count

        parent = ResourceResolver(registry)
        parent_val = await _resolve(
            parent,
            "case_val",
            consumer_spec=_consumer_spec(),
        )
        assert parent_val == 1

        child = parent.fork_for_test()
        child_val = await _resolve(
            child,
            "case_val",
            consumer_spec=_consumer_spec(),
        )
        assert child_val == 2  # New instance for child

    @pytest.mark.parametrize(
        ("scope", "name"),
        [
            (Scope.MODULE, "shared_module"),
            (Scope.RUN, "shared_process"),
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

        if scope == Scope.MODULE:

            @resource(scope=scope)
            async def shared_module():
                nonlocal create_count, teardown_count
                create_count += 1
                await asyncio.sleep(0.02)
                yield f"{scope.value}_{create_count}"
                teardown_count += 1

        else:

            @resource(scope=scope)
            async def shared_process():
                nonlocal create_count, teardown_count
                create_count += 1
                await asyncio.sleep(0.02)
                yield f"{scope.value}_{create_count}"
                teardown_count += 1

        parent = ResourceResolver(registry)
        children = [parent.fork_for_test() for _ in range(8)]
        values = await asyncio.gather(
            *[
                _resolve(child, name, consumer_spec=_consumer_spec())
                for child in children
            ]
        )

        assert values == [f"{scope.value}_1"] * len(children)
        assert create_count == 1

        await parent.teardown()
        assert teardown_count == 1


class TestHierarchicalProcessResources:
    """Tests for conftest-style RUN resource lookup."""

    @pytest.mark.asyncio
    async def test_nearest_ancestor_process_resource_wins(self, tmp_path):
        root = tmp_path / "project"
        child = root / "tests" / "child"
        root.mkdir(parents=True)
        child.mkdir(parents=True)

        _register_resource_source(
            root / "confrue_root.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "root"
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "child"
            """,
        )

        resolver = ResourceResolver(registry)

        assert (
            await _resolve(
                resolver,
                "shared",
                consumer_spec=_consumer_spec(
                    module_path=root / "tests" / "rue_root.py"
                ),
            )
            == "root"
        )

        assert (
            await _resolve(
                resolver,
                "shared",
                consumer_spec=_consumer_spec(
                    module_path=child / "rue_child.py"
                ),
            )
            == "child"
        )

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
            @resource(scope=Scope.RUN)
            def shared():
                return "root"
            """,
        )
        _register_resource_source(
            branch / "confrue_branch.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "branch"
            """,
        )

        resolver = ResourceResolver(registry)
        assert (
            await _resolve(
                resolver,
                "shared",
                consumer_spec=_consumer_spec(
                    module_path=sibling / "rue_sibling.py"
                ),
            )
            == "root"
        )

    @pytest.mark.asyncio
    async def test_run_dependency_uses_resource_provider_context(
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
            @resource(scope=Scope.RUN)
            def shared():
                return "root"

            @resource(scope=Scope.RUN)
            def consumer(shared):
                return f"consumer:{shared}"
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "child"
            """,
        )

        resolver = ResourceResolver(registry)
        assert (
            await _resolve(
                resolver,
                "consumer",
                consumer_spec=_consumer_spec(
                    module_path=child / "rue_child.py"
                ),
            )
            == "consumer:root"
        )

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
            @resource(scope=Scope.RUN)
            def shared():
                return "root"
            """,
        )
        _register_resource_source(
            child / "confrue_child.py",
            """
            @resource(scope=Scope.RUN)
            def shared():
                return "child"
            """,
        )

        resolver = ResourceResolver(registry)
        assert (
            await _resolve(resolver, "shared", consumer_spec=_consumer_spec())
            == "child"
        )

    @pytest.mark.asyncio
    async def test_hierarchical_process_resources_use_distinct_cache_keys(
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

            @resource(scope=Scope.RUN)
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

            @resource(scope=Scope.RUN)
            def shared():
                builtins.session_events.append("child_create")
                yield "child"
                builtins.session_events.append("child_teardown")
            """,
        )

        resolver = ResourceResolver(registry)

        assert (
            await _resolve(
                resolver,
                "shared",
                consumer_spec=_consumer_spec(
                    module_path=root / "tests" / "rue_root.py"
                ),
            )
            == "root"
        )

        assert (
            await _resolve(
                resolver,
                "shared",
                consumer_spec=_consumer_spec(
                    module_path=child / "rue_child.py"
                ),
            )
            == "child"
        )

        assert (
            await _resolve(
                resolver,
                "shared",
                consumer_spec=_consumer_spec(
                    module_path=root / "tests" / "rue_root.py"
                ),
            )
            == "root"
        )

        cache_keys = [
            key
            for key in resolver._cache
            if key.scope == Scope.RUN
            and key.locator.function_name == "shared"
        ]
        assert len(cache_keys) == 2
        assert {key.locator.module_path.parent for key in cache_keys} == {
            root.resolve(),
            child.resolve(),
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
        value = await _resolve(
            resolver,
            "doubled",
            consumer_spec=_consumer_spec(),
        )

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
        await _resolve(resolver, "simple", consumer_spec=_consumer_spec())
        await _resolve(resolver, "simple", consumer_spec=_consumer_spec())

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
        await _resolve(resolver, "gen_res", consumer_spec=_consumer_spec())
        await resolver.teardown()

        assert call_order == [("generator_teardown",), ("hook", "value")]

    @pytest.mark.asyncio
    async def test_on_teardown_with_teardown_scope(self):
        teardown_hook_called = False

        def on_teardown_hook(value):
            nonlocal teardown_hook_called
            teardown_hook_called = True

        @resource(scope="test", on_teardown=on_teardown_hook)
        def case_gen():
            yield "case_value"

        resolver = ResourceResolver(registry)
        await _resolve(resolver, "case_gen", consumer_spec=_consumer_spec())

        assert not teardown_hook_called
        await resolver.teardown_scope(Scope.TEST)
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

        @resource(
            on_injection=on_injection_hook,
            on_teardown=on_teardown_hook,
        )
        async def async_gen():
            yield "async_value"

        resolver = ResourceResolver(registry)
        value = await _resolve(
            resolver,
            "async_gen",
            consumer_spec=_consumer_spec(),
        )

        assert value == "async_value"
        assert injection_value == "async_value"

        await resolver.teardown()
        assert teardown_value == "async_value"

    @pytest.mark.asyncio
    async def test_on_injection_receives_custom_context(self):
        received_name = None

        def hook(value):
            nonlocal received_name
            received_name = (
                CURRENT_RESOURCE_TRANSACTION.get()
                .consumer_spec.locator.function_name
            )
            return value

        @resource(on_injection=hook)
        def simple():
            return 42

        resolver = ResourceResolver(registry)
        await _resolve(
            resolver,
            "simple",
            consumer_spec=_consumer_spec(name="my_test"),
        )
        assert received_name == "my_test"

    @pytest.mark.asyncio
    async def test_nested_dependency_context(self):
        history = []

        def hook(value):
            transaction = CURRENT_RESOURCE_TRANSACTION.get()
            history.append(
                (transaction.consumer_spec.locator.function_name, value)
            )
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
        await _resolve(resolver, "top", consumer_spec=_consumer_spec())

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
        await _resolve(resolver, "cached_res", consumer_spec=_consumer_spec())
        await _resolve(resolver, "cached_res", consumer_spec=_consumer_spec())

        # Hook called twice, once for each injection
        assert call_count == 2


class TestResourceResolutionErrors:
    """Tests to ensure resource resolution errors are properly surfaced."""

    def test_compile_graph_raises_for_unknown_resource(self):
        with pytest.raises(ValueError, match="Unknown resource: unknown"):
            registry.compile_graph(
                {
                    "test": (
                        _consumer_spec(module_path=Path("tests/test_sample.py")),
                        ("unknown",),
                    )
                }
            )

    @pytest.mark.asyncio
    async def test_circular_suite_dependency_raises_error(self):
        @resource(scope="module")
        async def shared_left(shared_right):
            return shared_right

        @resource(scope="module")
        async def shared_right(shared_left):
            return shared_left

        with pytest.raises(
            RuntimeError, match="Circular resource dependency detected"
        ):
            registry.compile_graph(
                {"test": (_consumer_spec(), ("shared_left",))}
            )

    def test_compile_graph_raises_for_circular_dependency(self):
        @resource(scope="module")
        def shared_left(shared_right):
            return shared_right

        @resource(scope="module")
        def shared_right(shared_left):
            return shared_left

        with pytest.raises(
            RuntimeError, match="Circular resource dependency detected"
        ):
            registry.compile_graph(
                {
                    "test": (
                        _consumer_spec(module_path=Path("tests/test_sample.py")),
                        ("shared_left",),
                    )
                }
            )

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
            await _resolve(
                resolver,
                "resource_with_injection",
                consumer_spec=_consumer_spec(),
            )

    @pytest.mark.asyncio
    async def test_teardown_errors_are_aggregated(self):
        def raise_on_teardown(_value):
            raise RuntimeError("hook teardown failed")

        @resource(scope=Scope.TEST, on_teardown=raise_on_teardown)
        def resource_with_teardown_errors():
            yield "value"
            raise RuntimeError("generator teardown failed")

        resolver = ResourceResolver(registry)
        assert (
            await _resolve(
                resolver,
                "resource_with_teardown_errors",
                consumer_spec=_consumer_spec(),
            )
            == "value"
        )

        with pytest.raises(ExceptionGroup) as exc_info:
            await resolver.teardown_scope(Scope.TEST)

        messages = {str(error) for error in exc_info.value.exceptions}
        assert any(
            "generator teardown failed" in message for message in messages
        )
        assert any("hook teardown failed" in message for message in messages)
