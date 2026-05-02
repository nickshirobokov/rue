"""Test runner for executing discovered tests."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.process_pool import LazyProcessPool
from rue.context.runtime import CURRENT_RUN_CONTEXT, TestContext, bind
from rue.events import RunEventsReceiver
from rue.resources import DependencyResolver
from rue.resources.metrics.base import MetricResult
from rue.resources.models import Scope
from rue.resources.sut.output import SUTOutputCapture
from rue.telemetry.otel.runtime import otel_runtime
from rue.testing.execution import DefaultTestFactory, SingleTest
from rue.testing.execution.queue import RunnerStep, SessionQueue
from rue.testing.models import (
    ExecutedTest,
    LoadedTestDef,
    Run,
)


class Runner:
    """Executes discovered tests with resource injection."""

    DEFAULT_MAX_CONCURRENCY = 10

    def __init__(
        self,
        *,
        capture_output: bool = True,
    ) -> None:
        self.capture_output = False

        self.semaphore: asyncio.Semaphore | None = None
        self.stop_flag: bool = False
        self._failure_count: int = 0
        self._queue = SessionQueue()
        self._completed_executions: dict[int, ExecutedTest] = {}
        self._remaining_module_leaves: dict[str, int] = {}

        self.current_run: Run | None = None

    def _concurrency_limit(self) -> int:
        context = CURRENT_RUN_CONTEXT.get()
        config = context.config
        return (
            config.concurrency
            if config.concurrency > 0
            else self.DEFAULT_MAX_CONCURRENCY
        )

    async def run(
        self,
        items: list[LoadedTestDef],
        *,
        resolver: DependencyResolver,
    ) -> Run:
        """Run tests and return results.

        Args:
            items: Test definitions to execute. Discover them with
                TestSpecCollector and TestLoader before calling.
            resolver: Resource resolver for this run. The runner owns teardown.

        Returns:
            Run with environment, results, and test executions.
        """
        context = CURRENT_RUN_CONTEXT.get()
        config = context.config
        self.current_run = Run(
            run_id=context.run_id,
            environment=context.environment,
        )
        receiver = RunEventsReceiver.current()
        await receiver.on_run_start(self.current_run)

        if config.otel:
            otel_runtime.configure()

        if not items:
            try:
                await receiver.on_no_tests_found()
                self.current_run.end_time = datetime.now(UTC)
                await receiver.on_run_complete()
                return self.current_run
            finally:
                await resolver.teardown()

        metric_results: list[MetricResult] = []
        start = time.perf_counter()

        with (
            SUTOutputCapture.sys_capture(swallow=self.capture_output),
            bind(CURRENT_METRIC_RESULTS, metric_results),
        ):
            try:
                await receiver.on_collection_complete(items)

                self.semaphore = asyncio.Semaphore(self._concurrency_limit())
                self.stop_flag = False
                self._failure_count = 0

                execution = self._execute_run(
                    items=items,
                    resolver=resolver,
                    run=self.current_run,
                )

                run_task = asyncio.create_task(execution)

                try:
                    if config.timeout is not None:
                        await asyncio.wait_for(
                            run_task, timeout=config.timeout
                        )
                    else:
                        await run_task
                except TimeoutError:
                    self.current_run.result.stopped_early = True
                    self.stop_flag = True
            finally:
                await resolver.teardown()

        self.current_run.result.total_duration_ms = (
            time.perf_counter() - start
        ) * 1000
        self.current_run.result.metric_results = metric_results.copy()
        self.current_run.end_time = datetime.now(UTC)

        await receiver.on_run_complete()

        return self.current_run

    async def _execute_run(
        self,
        *,
        items: list[LoadedTestDef],
        resolver: DependencyResolver,
        run: Run,
    ) -> None:
        """Execute the test run with the given items and resolver."""
        with LazyProcessPool(self._concurrency_limit()):
            self._queue = SessionQueue()
            self._factory = DefaultTestFactory(
                semaphore=self.semaphore,
                is_stopped=lambda: self.stop_flag,
                queue=self._queue,
            )
            for item in items:
                self._factory.build(item)
            leaves = [
                leaf
                for test in self._queue.tests
                for leaf in test.leaves()
                if isinstance(leaf, SingleTest)
            ]
            consumers = {
                leaf.execution_id: (
                    leaf.definition.spec,
                    tuple(
                        param
                        for param in leaf.definition.spec.params
                        if param not in leaf.params
                    ),
                )
                for leaf in leaves
            }
            autouse_keys = frozenset(consumers)
            graphs = resolver.registry.compile_graphs(
                consumers,
                autouse_keys=autouse_keys,
            )
            await RunEventsReceiver.current().on_di_graphs_compiled(graphs)
            self._remaining_module_leaves = {}
            for leaf in leaves:
                module_path = leaf.definition.spec.locator.module_path
                module_key = (
                    str(module_path.resolve())
                    if module_path is not None
                    else "<unknown>"
                )
                self._remaining_module_leaves[module_key] = (
                    self._remaining_module_leaves.get(module_key, 0) + 1
                )
            await RunEventsReceiver.current().on_tests_ready(self._queue.tests)
            self._completed_executions = {}
            context = CURRENT_RUN_CONTEXT.get()
            config = context.config
            try:
                for step in self._queue.steps:
                    if self.stop_flag:
                        break
                    await self._run_step(step, resolver, run)
                    if run.result.stopped_early and config.maxfail:
                        await RunEventsReceiver.current().on_run_stopped_early(
                            config.maxfail
                        )
                        break
            finally:
                run.result.executions = [
                    execution
                    for test in self._queue.tests
                    if (
                        execution := self._completed_executions.get(
                            test.definition.spec.collection_index
                        )
                    )
                    is not None
                ]

    async def _run_step(
        self,
        step: RunnerStep,
        resolver: DependencyResolver,
        run: Run,
    ) -> None:
        """Run one queue step."""
        if step.is_main:
            batch = step.main_batch
            if batch is None:
                return
            for test in batch.tests:
                if self.stop_flag:
                    break
                await RunEventsReceiver.current().on_test_start(test)
                execution = await test.execute(resolver)
                self._record_execution(run, execution)
                await self._teardown_module_if_complete(
                    resolver,
                    execution,
                )
            return

        condition = asyncio.Condition()

        async def worker() -> None:
            while True:
                async with condition:
                    while True:
                        if self.stop_flag:
                            return
                        queued = step.dequeue_ready()
                        if queued is not None:
                            break
                        if step.is_complete:
                            return
                        await condition.wait()
                    mq, batch, test = queued
                    await RunEventsReceiver.current().on_test_start(test)

                execution = await test.execute(resolver)
                self._record_execution(run, execution)
                await self._teardown_module_if_complete(
                    resolver,
                    execution,
                )

                async with condition:
                    step.finish(mq, batch)
                    condition.notify_all()

        workers = [
            asyncio.create_task(worker())
            for _ in range(
                min(self._concurrency_limit(), step.total_tests_count)
            )
        ]
        try:
            for task in asyncio.as_completed(workers):
                await task
        except Exception:
            for task in workers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise

    def _record_execution(
        self,
        run: Run,
        execution: ExecutedTest,
    ) -> None:
        self._completed_executions[
            execution.definition.spec.collection_index
        ] = execution
        if not execution.result.status.is_failure:
            return
        self._failure_count += 1
        context = CURRENT_RUN_CONTEXT.get()
        maxfail = context.config.maxfail
        if maxfail and self._failure_count >= maxfail:
            self.stop_flag = True
            run.result.stopped_early = True

    async def _teardown_module_if_complete(
        self,
        resolver: DependencyResolver,
        execution: ExecutedTest,
    ) -> None:
        module_path = execution.definition.spec.locator.module_path
        module_key = (
            str(module_path.resolve())
            if module_path is not None
            else "<unknown>"
        )
        remaining = self._remaining_module_leaves[module_key] - 1
        self._remaining_module_leaves[module_key] = remaining
        if remaining:
            return
        with TestContext(
            item=execution.definition,
            execution_id=execution.execution_id,
        ):
            await resolver.teardown(Scope.MODULE)
