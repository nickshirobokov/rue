"""Builder for `rue tests status` reports."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from rue.config import Config
from rue.context.runtime import CURRENT_TEST, TestContext, bind
from rue.resources import ResourceResolver, ResourceSpec
from rue.resources.metrics.base import Metric
from rue.resources.registry import registry as default_resource_registry
from rue.storage.sqlite import SQLiteStore
from rue.storage.sqlite.store import MAX_STORED_RUNS
from rue.testing.discovery import TestLoader
from rue.testing.models import (
    BackendModifier,
    CasesIterateModifier,
    GroupsIterateModifier,
    IterateModifier,
    LoadedTestDef,
    ParameterSet,
    ParamsIterateModifier,
    Run,
    SetupFileRef,
    TestSpec,
    TestSpecCollection,
    TestStatus,
)

from rue.cli.tests.status.models import (
    StatusIssue,
    StatusNode,
    TestsStatusReport,
    _DraftNode,
)


class TestsStatusBuilder:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._issues_by_key: dict[str, list[StatusIssue]] = defaultdict(list)

    def load_items(self, collection: TestSpecCollection) -> list[LoadedTestDef]:
        default_resource_registry.reset()
        self._issues_by_key = defaultdict(list)
        loader = TestLoader(collection.suite_root)
        items: list[LoadedTestDef] = []
        by_module: dict[Path, list[TestSpec]] = defaultdict(list)
        for spec in collection.specs:
            by_module[spec.module_path].append(spec)

        for module_path, specs in by_module.items():
            setup_chain = collection.setup_chain_for(module_path)
            setup_error = self._prepare_setup(loader, setup_chain)
            if setup_error is not None:
                items.extend(
                    self._placeholder_items(
                        specs,
                        collection.suite_root,
                        setup_chain,
                        setup_error,
                    )
                )
                continue

            for spec in specs:
                try:
                    items.append(
                        loader.load_definition(
                            spec,
                            setup_chain=setup_chain,
                        )
                    )
                except Exception as error:
                    items.extend(
                        self._placeholder_items(
                            [spec],
                            collection.suite_root,
                            setup_chain,
                            str(error),
                        )
                    )

        return items

    def build(
        self,
        collection: TestSpecCollection,
        items: list[LoadedTestDef],
        *,
        store: SQLiteStore | None,
    ) -> TestsStatusReport:
        drafts = [self._build_draft(item) for item in items]
        for draft in drafts:
            self._record_definition_issues(draft)

        if store is None:
            run_window: tuple[Run, ...] = ()
            history_by_key = {node_key: () for node_key in self._iter_node_keys(drafts)}
        else:
            run_window = tuple(store.list_runs(limit=MAX_STORED_RUNS))
            history_by_key = store.get_test_history(tuple(self._iter_node_keys(drafts)))
            self._apply_legacy_history(drafts, run_window, history_by_key)

        connected_by_key: dict[str, tuple[ResourceSpec, ...]] = {}
        leaves = self._iter_leaves(drafts)
        for leaf in leaves:
            connected_by_key[leaf.node_key] = self._collect_static_dependencies(
                leaf
            )

        resources_by_key, metrics_by_key = asyncio.run(
            self._preflight(leaves, connected_by_key)
        )

        module_nodes: dict[Path, list[StatusNode]] = defaultdict(list)
        for draft in drafts:
            module_nodes[draft.definition.spec.module_path].append(
                self._finalize_node(
                    draft,
                    history_by_key,
                    resources_by_key,
                    metrics_by_key,
                )
            )

        _ = collection
        return TestsStatusReport(run_window=run_window, module_nodes=dict(module_nodes))

    def _prepare_setup(
        self,
        loader: TestLoader,
        setup_chain: tuple[SetupFileRef, ...],
    ) -> str | None:
        for setup_ref in setup_chain:
            try:
                loader.prepare_setup(setup_ref.path)
            except Exception as error:
                return str(error)
        return None

    def _placeholder_items(
        self,
        specs: list[TestSpec],
        suite_root: Path,
        setup_chain: tuple[SetupFileRef, ...],
        message: str,
    ) -> list[LoadedTestDef]:
        items: list[LoadedTestDef] = []
        for spec in specs:
            self._add_issue(spec.full_name, "load", message)
            items.append(
                LoadedTestDef(
                    spec=replace(spec, definition_error=message),
                    fn=lambda: None,
                    suite_root=suite_root,
                    setup_chain=setup_chain,
                )
            )
        return items

    def _build_draft(
        self,
        definition: LoadedTestDef,
        *,
        backend: str = "asyncio",
        params: dict[str, Any] | None = None,
        node_key: str | None = None,
    ) -> _DraftNode:
        params = params or {}
        node_key = node_key or definition.spec.full_name
        modifiers = definition.spec.modifiers
        if not modifiers:
            return _DraftNode(
                definition=definition,
                backend=backend,
                params=dict(params),
                node_key=node_key,
            )

        modifier, *rest = modifiers
        rest_tuple = tuple(rest)

        match modifier:
            case BackendModifier(backend=sub_backend):
                return self._build_draft(
                    replace(
                        definition,
                        spec=replace(definition.spec, modifiers=rest_tuple),
                    ),
                    backend=getattr(sub_backend, "value", str(sub_backend)),
                    params=params,
                    node_key=node_key,
                )
            case IterateModifier(count=count):
                children = tuple(
                    self._build_draft(
                        replace(
                            definition,
                            spec=replace(
                                definition.spec,
                                modifiers=rest_tuple,
                                suffix=f"iterate={index}",
                            ),
                        ),
                        backend=backend,
                        params=params,
                        node_key=self._child_node_key(
                            node_key,
                            modifier.display_name,
                            index,
                        ),
                    )
                    for index in range(count)
                )
            case ParamsIterateModifier(parameter_sets=parameter_sets):
                children = tuple(
                    self._build_param_child(
                        definition,
                        rest_tuple,
                        backend,
                        params,
                        node_key,
                        modifier.display_name,
                        index,
                        parameter_set,
                    )
                    for index, parameter_set in enumerate(parameter_sets)
                )
            case CasesIterateModifier(cases=cases):
                children = tuple(
                    self._build_case_child(
                        definition,
                        rest_tuple,
                        backend,
                        params,
                        node_key,
                        modifier.display_name,
                        index,
                        case,
                    )
                    for index, case in enumerate(cases)
                )
            case GroupsIterateModifier(groups=groups):
                children = tuple(
                    self._build_group_child(
                        definition,
                        rest_tuple,
                        backend,
                        params,
                        node_key,
                        modifier.display_name,
                        index,
                        group,
                    )
                    for index, group in enumerate(groups)
                )
            case _:
                msg = f"Unknown modifier: {type(modifier).__name__}"
                raise NotImplementedError(msg)

        return _DraftNode(
            definition=definition,
            backend=backend,
            params=dict(params),
            node_key=node_key,
            children=children,
        )

    def _build_param_child(
        self,
        definition: LoadedTestDef,
        rest_tuple: tuple,
        backend: str,
        params: dict[str, Any],
        node_key: str,
        display_name: str,
        index: int,
        parameter_set: ParameterSet,
    ) -> _DraftNode:
        return self._build_draft(
            replace(
                definition,
                spec=replace(
                    definition.spec,
                    modifiers=rest_tuple,
                    suffix=parameter_set.suffix,
                ),
            ),
            backend=backend,
            params={**params, **parameter_set.values},
            node_key=self._child_node_key(
                node_key,
                display_name,
                index,
                parameter_set.suffix,
            ),
        )

    def _build_case_child(
        self,
        definition: LoadedTestDef,
        rest_tuple: tuple,
        backend: str,
        params: dict[str, Any],
        node_key: str,
        display_name: str,
        index: int,
        case: Any,
    ) -> _DraftNode:
        label = repr(case.metadata) if case.metadata else None
        return self._build_draft(
            replace(
                definition,
                spec=replace(
                    definition.spec,
                    modifiers=rest_tuple,
                    suffix=label,
                    case_id=case.id,
                ),
            ),
            backend=backend,
            params={**params, "case": case},
            node_key=self._child_node_key(
                node_key,
                display_name,
                index,
                label,
            ),
        )

    def _build_group_child(
        self,
        definition: LoadedTestDef,
        rest_tuple: tuple,
        backend: str,
        params: dict[str, Any],
        node_key: str,
        display_name: str,
        index: int,
        group: Any,
    ) -> _DraftNode:
        return self._build_draft(
            replace(
                definition,
                spec=replace(
                    definition.spec,
                    modifiers=(
                        CasesIterateModifier(
                            cases=tuple(group.cases),
                            min_passes=group.min_passes,
                        ),
                        *rest_tuple,
                    ),
                    suffix=group.name,
                ),
            ),
            backend=backend,
            params={**params, "group": group},
            node_key=self._child_node_key(
                node_key,
                display_name,
                index,
                group.name,
            ),
        )

    def _child_node_key(
        self,
        node_key: str,
        modifier_name: str,
        index: int,
        label: str | None = None,
    ) -> str:
        segment = f"{modifier_name}[{index}]"
        if label:
            segment = f"{segment}={label}"
        return f"{node_key}/{segment}"

    def _record_definition_issues(self, node: _DraftNode) -> None:
        if node.definition.spec.definition_error:
            self._add_issue(
                node.node_key,
                "definition",
                node.definition.spec.definition_error,
            )
        for child in node.children:
            self._record_definition_issues(child)

    def _collect_static_dependencies(
        self,
        leaf: _DraftNode,
    ) -> tuple[ResourceSpec, ...]:
        connected: dict[str, ResourceSpec] = {}
        unresolved = tuple(
            param for param in leaf.definition.spec.params if param not in leaf.params
        )
        request_path = leaf.definition.spec.module_path.resolve()

        def visit(name: str, path: tuple[ResourceSpec, ...]) -> None:
            try:
                definition = default_resource_registry.select(
                    name,
                    request_path,
                ).definition
            except Exception as error:
                self._add_issue(leaf.node_key, "resolve", str(error))
                return

            identity = definition.spec
            if identity in path:
                cycle = " -> ".join(
                    (
                        f"{key.scope.value}:{key.name}"
                        if key.provider_dir is None
                        else f"{key.scope.value}:{key.name}@{key.provider_dir}"
                    )
                    for key in (*path, identity)
                )
                self._add_issue(
                    leaf.node_key,
                    "resolve",
                    f"Circular resource dependency detected: {cycle}",
                )
                return

            if identity.snapshot_key in connected:
                return
            connected[identity.snapshot_key] = identity
            for dependency in identity.dependencies:
                visit(dependency, (*path, identity))

        for param in unresolved:
            visit(param, ())

        return tuple(sorted(connected.values(), key=_resource_sort_key))

    async def _preflight(
        self,
        leaves: list[_DraftNode],
        connected_by_key: dict[str, tuple[ResourceSpec, ...]],
    ) -> tuple[
        dict[str, tuple[ResourceSpec, ...]],
        dict[str, tuple[ResourceSpec, ...]],
    ]:
        resources_by_key: dict[str, tuple[ResourceSpec, ...]] = {}
        metrics_by_key: dict[str, tuple[ResourceSpec, ...]] = {}
        for leaf in leaves:
            connected = connected_by_key[leaf.node_key]
            if self._has_blocking_issue(leaf.node_key):
                resources_by_key[leaf.node_key] = connected
                metrics_by_key[leaf.node_key] = ()
                continue
            resolver = ResourceResolver(default_resource_registry)
            unresolved = tuple(
                param for param in leaf.definition.spec.params if param not in leaf.params
            )
            ctx = TestContext(item=leaf.definition, execution_id=uuid4())
            try:
                with bind(CURRENT_TEST, ctx):
                    await resolver.partially_resolve(unresolved, leaf.params)
            except Exception as error:
                self._add_issue(leaf.node_key, "resolve", str(error))
            finally:
                resources_by_key[leaf.node_key], metrics_by_key[leaf.node_key] = (
                    self._split_connected_identities(
                        connected,
                        resolver.cached_identities,
                    )
                )
                try:
                    with bind(CURRENT_TEST, ctx):
                        await resolver.teardown()
                except Exception as error:
                    self._add_issue(leaf.node_key, "resolve", str(error))
        return resources_by_key, metrics_by_key

    def _split_connected_identities(
        self,
        connected: tuple[ResourceSpec, ...],
        cached: dict[ResourceSpec, Any],
    ) -> tuple[tuple[ResourceSpec, ...], tuple[ResourceSpec, ...]]:
        resources: list[ResourceSpec] = []
        metrics: list[ResourceSpec] = []
        for identity in connected:
            value = cached.get(identity)
            if isinstance(value, Metric):
                metrics.append(identity)
                continue
            resources.append(identity)
        return tuple(resources), tuple(metrics)

    def _has_blocking_issue(self, node_key: str) -> bool:
        return any(
            issue.phase in {"load", "definition"}
            for issue in self._issues_by_key.get(node_key, [])
        )

    def _apply_legacy_history(
        self,
        drafts: list[_DraftNode],
        run_window: tuple[Run, ...],
        history_by_key: dict[str, tuple[TestStatus | None, ...]],
    ) -> None:
        for node in self._iter_nodes(drafts):
            history = list(
                history_by_key.get(node.node_key, (None,) * MAX_STORED_RUNS)
            )
            for index, run in enumerate(run_window):
                if history[index] is not None:
                    continue
                status = self._find_legacy_status(node, run.result.executions)
                if status is not None:
                    history[index] = status
            history_by_key[node.node_key] = tuple(history)

    def _find_legacy_status(
        self,
        node: _DraftNode,
        executions: list[Any],
    ) -> TestStatus | None:
        spec = node.definition.spec
        if node.node_key != spec.full_name and (
            spec.suffix is None or "=" not in node.node_key.rsplit("/", 1)[-1]
        ):
            return None

        for execution in executions:
            exec_spec = execution.definition.spec
            if (
                exec_spec.module_path == spec.module_path
                and exec_spec.class_name == spec.class_name
                and exec_spec.name == spec.name
                and exec_spec.suffix == spec.suffix
            ):
                return execution.status
            match = self._find_legacy_status(node, execution.sub_executions)
            if match is not None:
                return match
        return None

    def _iter_node_keys(self, drafts: list[_DraftNode]) -> list[str]:
        return [node.node_key for node in self._iter_nodes(drafts)]

    def _iter_nodes(self, drafts: list[_DraftNode]) -> list[_DraftNode]:
        nodes: list[_DraftNode] = []
        for draft in drafts:
            nodes.append(draft)
            nodes.extend(self._iter_nodes(list(draft.children)))
        return nodes

    def _iter_leaves(self, drafts: list[_DraftNode]) -> list[_DraftNode]:
        leaves: list[_DraftNode] = []
        for draft in drafts:
            if not draft.children:
                leaves.append(draft)
                continue
            leaves.extend(self._iter_leaves(list(draft.children)))
        return leaves

    def _add_issue(
        self,
        node_key: str,
        phase: Literal["load", "definition", "resolve"],
        message: str,
    ) -> None:
        if any(
            issue.phase == phase and issue.message == message
            for issue in self._issues_by_key[node_key]
        ):
            return
        self._issues_by_key[node_key].append(
            StatusIssue(phase=phase, message=message, node_key=node_key)
        )

    def _finalize_node(
        self,
        draft: _DraftNode,
        history_by_key: dict[str, tuple[TestStatus | None, ...]],
        resources_by_key: dict[str, tuple[ResourceSpec, ...]],
        metrics_by_key: dict[str, tuple[ResourceSpec, ...]],
    ) -> StatusNode:
        children = tuple(
            self._finalize_node(
                child,
                history_by_key,
                resources_by_key,
                metrics_by_key,
            )
            for child in draft.children
        )
        leaf_count = sum(child.leaf_count for child in children) if children else 1
        return StatusNode(
            definition=draft.definition,
            backend=draft.backend,
            history=history_by_key.get(draft.node_key, ()),
            issues=tuple(self._issues_by_key.get(draft.node_key, ())),
            resources=resources_by_key.get(draft.node_key, ()),
            metrics=metrics_by_key.get(draft.node_key, ()),
            children=children,
            leaf_count=leaf_count,
        )


def _resource_sort_key(spec: ResourceSpec) -> tuple[int, str, str, str]:
    return (
        {"process": 0, "module": 1, "test": 2}.get(spec.scope.value, 99),
        spec.name,
        spec.provider_path or "",
        spec.provider_dir or "",
    )


__all__ = ["TestsStatusBuilder"]
