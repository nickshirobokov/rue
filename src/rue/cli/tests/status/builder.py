"""Builder for `rue tests status` reports."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Literal
from uuid import UUID

from rue.cli.tests.status.models import (
    StatusIssue,
    StatusNode,
    TestsStatusReport,
)
from rue.config import Config
from rue.context.runtime import RunContext, TestContext
from rue.events.receiver import RunEventsReceiver
from rue.resources import DependencyResolver, ResourceSpec
from rue.resources.models import ResourceGraph
from rue.resources.registry import registry as default_resource_registry
from rue.storage.sqlite import SQLiteStore
from rue.testing.discovery import TestLoader
from rue.testing.execution.base import ExecutableTest
from rue.testing.execution.factory import DefaultTestFactory
from rue.testing.execution.single import SingleTest
from rue.testing.models import TestSpecCollection


class TestsStatusBuilder:
    """Build status reports from discovered tests."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._issues_by_execution_id: dict[
            UUID, list[StatusIssue]
        ] = defaultdict(list)

    def build(
        self,
        collection: TestSpecCollection,
        *,
        store: SQLiteStore | None,
    ) -> TestsStatusReport:
        """Return the current test status report for a collection."""
        default_resource_registry.reset()
        self._issues_by_execution_id = defaultdict(list)

        items = TestLoader(collection.suite_root).load_from_collection(
            collection
        )
        context = RunContext(config=self.config)
        with context, RunEventsReceiver([]):
            factory = DefaultTestFactory()
            tests = [factory.build(item, enqueue=False) for item in items]

            leaves = [
                leaf
                for test in tests
                for leaf in test.leaves()
                if isinstance(leaf, SingleTest)
            ]
            connected_by_execution_id, graphs_by_execution_id = (
                self._collect_static_dependencies(leaves)
            )
            resources_by_execution_id = asyncio.run(
                self._preflight(
                    leaves,
                    connected_by_execution_id,
                    graphs_by_execution_id,
                )
            )

            module_nodes: dict[Path, list[StatusNode]] = defaultdict(list)
            for test in tests:
                module_nodes[test.definition.spec.locator.module_path].append(
                    self._finalize_node(
                        test,
                        resources_by_execution_id,
                    )
                )

            return TestsStatusReport(
                run_window=(),
                module_nodes=dict(module_nodes),
            )

    def _collect_static_dependencies(
        self,
        leaves: list[SingleTest],
    ) -> tuple[
        dict[UUID, tuple[ResourceSpec, ...]],
        dict[UUID, ResourceGraph],
    ]:
        connected_by_execution_id: dict[UUID, tuple[ResourceSpec, ...]] = {}
        graphs_by_execution_id: dict[UUID, ResourceGraph] = {}
        for leaf in leaves:
            try:
                graphs = default_resource_registry.compile_graphs(
                    {
                        leaf.execution_id: (
                            leaf.definition.spec,
                            tuple(
                                param
                                for param in leaf.definition.spec.params
                                if param not in leaf.params
                            ),
                        )
                    },
                    autouse_keys=frozenset({leaf.execution_id}),
                )
                graph = graphs[leaf.execution_id]
                graphs_by_execution_id[leaf.execution_id] = graph
                connected_by_execution_id[leaf.execution_id] = (
                    graph.resolution_order
                )
            except Exception as error:
                self._add_issue(leaf.execution_id, "resolve", str(error))
                connected_by_execution_id[leaf.execution_id] = ()
        return connected_by_execution_id, graphs_by_execution_id

    async def _preflight(
        self,
        leaves: list[SingleTest],
        connected_by_execution_id: dict[UUID, tuple[ResourceSpec, ...]],
        graphs_by_execution_id: dict[UUID, ResourceGraph],
    ) -> dict[UUID, dict[str, tuple[ResourceSpec, ...]]]:
        resources_by_execution_id: dict[
            UUID, dict[str, tuple[ResourceSpec, ...]]
        ] = {}

        for leaf in leaves:
            execution_id = leaf.execution_id
            connected = connected_by_execution_id[execution_id]
            if execution_id not in graphs_by_execution_id:
                resources_by_execution_id[execution_id] = {}
                continue

            resolver = DependencyResolver(default_resource_registry)
            graph = graphs_by_execution_id[execution_id]
            visible_resources = {}
            try:
                with TestContext(
                    item=leaf.definition,
                    execution_id=execution_id,
                ):
                    await resolver.resolve_graph_deps(
                        graph,
                        leaf.params,
                        consumer_spec=leaf.definition.spec,
                    )
                    visible_resources = resolver.resources.visible_instances()
            except Exception as error:
                self._add_issue(execution_id, "resolve", str(error))
            finally:
                grouped_resources: dict[str, list[ResourceSpec]] = {}
                for spec in connected:
                    value = visible_resources.get(spec)
                    if value is None:
                        continue
                    grouped_resources.setdefault(
                        type(value).__name__,
                        [],
                    ).append(spec)
                resources_by_execution_id[execution_id] = {
                    type_name: tuple(specs)
                    for type_name, specs in grouped_resources.items()
                }
                try:
                    await resolver.teardown()
                except Exception as error:
                    self._add_issue(execution_id, "resolve", str(error))

        return resources_by_execution_id

    def _add_issue(
        self,
        execution_id: UUID,
        phase: Literal["resolve"],
        message: str,
    ) -> None:
        if any(
            issue.phase == phase and issue.message == message
            for issue in self._issues_by_execution_id[execution_id]
        ):
            return
        self._issues_by_execution_id[execution_id].append(
            StatusIssue(phase=phase, message=message)
        )

    def _finalize_node(
        self,
        test: ExecutableTest,
        resources_by_execution_id: dict[
            UUID, dict[str, tuple[ResourceSpec, ...]]
        ],
    ) -> StatusNode:
        children = tuple(
            self._finalize_node(
                child,
                resources_by_execution_id,
            )
            for child in test.children
        )
        leaf_count = (
            sum(child.leaf_count for child in children) if children else 1
        )
        return StatusNode(
            definition=test.definition,
            backend=test.backend,
            history=(),
            issues=tuple(
                self._issues_by_execution_id.get(test.execution_id, ())
            ),
            resources_by_type=resources_by_execution_id.get(
                test.execution_id, {}
            ),
            children=children,
            leaf_count=leaf_count,
        )


__all__ = ["TestsStatusBuilder"]
