"""Builder for `rue tests status` reports."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from rue.cli.tests.status.models import StatusIssue, StatusNode, TestsStatusReport
from rue.config import Config
from rue.context.runtime import CURRENT_TEST, TestContext, bind
from rue.resources import ResourceResolver, ResourceSpec
from rue.resources.metrics.base import Metric
from rue.resources.registry import registry as default_resource_registry
from rue.storage.sqlite import SQLiteStore
from rue.storage.sqlite.store import MAX_STORED_RUNS
from rue.testing.discovery import TestLoader
from rue.testing.execution.base import ExecutableTest
from rue.testing.execution.factory import DefaultTestFactory
from rue.testing.execution.single import SingleTest
from rue.testing.models import Run, TestSpecCollection, TestStatus


class TestsStatusBuilder:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._issues_by_key: dict[str, list[StatusIssue]] = defaultdict(list)

    def build(
        self,
        collection: TestSpecCollection,
        *,
        store: SQLiteStore | None,
    ) -> TestsStatusReport:
        default_resource_registry.reset()
        self._issues_by_key = defaultdict(list)

        items = TestLoader(collection.suite_root).load_from_collection_unsafe(
            collection
        )
        factory = DefaultTestFactory(config=self.config, run_id=uuid4())
        tests = [factory.build(item, enqueue=False) for item in items]

        for test in tests:
            self._record_issues(test)

        if store is None:
            run_window: tuple[Run, ...] = ()
            history_by_key = {
                node.node_key: ()
                for test in tests
                for node in test.walk()
            }
        else:
            run_window = tuple(store.list_runs(limit=MAX_STORED_RUNS))
            history_by_key = store.get_test_history_for_tests(
                tests,
                limit=MAX_STORED_RUNS,
            )

        leaves = [
            leaf
            for test in tests
            for leaf in test.leaves()
            if isinstance(leaf, SingleTest)
        ]
        connected_by_key = self._collect_static_dependencies(leaves)
        resources_by_key, metrics_by_key = asyncio.run(
            self._preflight(leaves, connected_by_key)
        )

        module_nodes: dict[Path, list[StatusNode]] = defaultdict(list)
        for test in tests:
            module_nodes[test.definition.spec.module_path].append(
                self._finalize_node(
                    test,
                    history_by_key,
                    resources_by_key,
                    metrics_by_key,
                )
            )

        return TestsStatusReport(
            run_window=run_window,
            module_nodes=dict(module_nodes),
        )

    def _record_issues(self, root: ExecutableTest) -> None:
        for test in root.walk():
            if (
                test.definition.load_error
                and test.node_key == test.definition.spec.full_name
            ):
                self._add_issue(
                    test.node_key,
                    "load",
                    test.definition.load_error,
                )
            if test.definition.spec.definition_error:
                self._add_issue(
                    test.node_key,
                    "definition",
                    test.definition.spec.definition_error,
                )

    def _collect_static_dependencies(
        self,
        leaves: list[SingleTest],
    ) -> dict[str, tuple[ResourceSpec, ...]]:
        resolver = ResourceResolver(default_resource_registry)
        connected_by_key: dict[str, tuple[ResourceSpec, ...]] = {}
        for leaf in leaves:
            try:
                connected_by_key[leaf.node_key] = (
                    resolver.collect_dependency_closure(
                        tuple(
                            param
                            for param in leaf.definition.spec.params
                            if param not in leaf.params
                        ),
                        request_path=leaf.definition.spec.module_path.resolve(),
                    )
                )
            except Exception as error:
                self._add_issue(leaf.node_key, "resolve", str(error))
                connected_by_key[leaf.node_key] = ()
        return connected_by_key

    async def _preflight(
        self,
        leaves: list[SingleTest],
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
            ctx = TestContext(item=leaf.definition, execution_id=uuid4())
            try:
                with bind(CURRENT_TEST, ctx):
                    await resolver.partially_resolve(
                        tuple(
                            param
                            for param in leaf.definition.spec.params
                            if param not in leaf.params
                        ),
                        leaf.params,
                    )
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
        test: ExecutableTest,
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
            for child in test.children
        )
        leaf_count = sum(child.leaf_count for child in children) if children else 1
        return StatusNode(
            definition=test.definition,
            backend=test.backend,
            history=history_by_key.get(test.node_key, ()),
            issues=tuple(self._issues_by_key.get(test.node_key, ())),
            resources=resources_by_key.get(test.node_key, ()),
            metrics=metrics_by_key.get(test.node_key, ()),
            children=children,
            leaf_count=leaf_count,
        )


__all__ = ["TestsStatusBuilder"]
