"""Executable suite execution orchestration."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.process_pool import LazyProcessPool
from rue.context.runtime import CURRENT_SUITE_CONTEXT, ModuleContext, bind
from rue.context.scopes import Scope
from rue.events import SuiteEventsReceiver
from rue.resources import DependencyResolver
from rue.resources.metrics.models import MetricResult
from rue.telemetry.otel.runtime import otel_runtime
from rue.testing.compilation.factory import DefaultTestFactory
from rue.testing.compilation.queue import SuiteQueue, _SuiteStep
from rue.testing.execution.models import ExecutedTest, LoadedTestDef
from rue.testing.execution.suite.models import ExecutedSuite
from rue.testing.execution.test.base import ExecutableTest
from rue.testing.execution.test.single import SingleTest


@dataclass
class ExecutableSuite:
    """Loaded suite with the dependencies needed to execute it."""

    DEFAULT_MAX_CONCURRENCY = 10

    items: list[LoadedTestDef]
    suite_execution_id: UUID
    resolver: DependencyResolver
    semaphore: asyncio.Semaphore | None = field(default=None, init=False)
    stop_flag: bool = field(default=False, init=False)
    _failure_count: int = field(default=0, init=False)
    _queue: SuiteQueue = field(default_factory=SuiteQueue, init=False)
    _completed_test_executions: dict[int, ExecutedTest] = field(
        default_factory=dict,
        init=False,
    )
    _factory: DefaultTestFactory | None = field(default=None, init=False)
    result: ExecutedSuite | None = field(default=None, init=False)

    def _concurrency_limit(self) -> int:
        context = CURRENT_SUITE_CONTEXT.get()
        config = context.config
        return (
            config.concurrency
            if config.concurrency > 0
            else self.DEFAULT_MAX_CONCURRENCY
        )

    async def execute(self) -> ExecutedSuite:
        """Execute this suite and return results."""
        context = CURRENT_SUITE_CONTEXT.get()
        config = context.config
        self.result = ExecutedSuite(
            suite_execution_id=self.suite_execution_id,
            environment=context.environment,
        )
        receiver = SuiteEventsReceiver.current()
        await receiver.on_suite_execution_start(self.result)

        if config.otel:
            otel_runtime.configure()

        if not self.items:
            try:
                await receiver.on_no_tests_found()
                self.result.end_time = datetime.now(UTC)
                await receiver.on_suite_execution_complete()
                return self.result
            finally:
                await self.resolver.teardown()

        metric_results: list[MetricResult] = []
        start = time.perf_counter()

        with bind(CURRENT_METRIC_RESULTS, metric_results):
            try:
                await receiver.on_collection_complete(self.items)

                self.semaphore = asyncio.Semaphore(self._concurrency_limit())
                self.stop_flag = False
                self._failure_count = 0

                execution = self._execute_suite(
                    suite=self.result,
                )

                suite_task = asyncio.create_task(execution)

                try:
                    if config.timeout is not None:
                        await asyncio.wait_for(
                            suite_task, timeout=config.timeout
                        )
                    else:
                        await suite_task
                except TimeoutError:
                    self.result.result.stopped_early = True
                    self.stop_flag = True
            finally:
                await self.resolver.teardown()

        self.result.result.total_duration_ms = (
            time.perf_counter() - start
        ) * 1000
        self.result.result.metric_results = metric_results.copy()
        self.result.end_time = datetime.now(UTC)

        await receiver.on_suite_execution_complete()

        return self.result

    async def _execute_suite(
        self,
        *,
        suite: ExecutedSuite,
    ) -> None:
        """Execute the suite with the given items and resolver."""
        with LazyProcessPool(self._concurrency_limit()):
            self._queue = SuiteQueue()
            self._factory = DefaultTestFactory(
                semaphore=self.semaphore,
                is_stopped=lambda: self.stop_flag,
                queue=self._queue,
            )
            for item in self.items:
                self._factory.build(item)
            leaves = [
                leaf
                for test in self._queue.tests
                for leaf in test.leaves()
                if isinstance(leaf, SingleTest)
            ]
            consumers = {
                leaf.test_execution_id: (
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
            graphs = self.resolver.registry.compile_graphs(
                consumers,
                autouse_keys=autouse_keys,
            )
            await SuiteEventsReceiver.current().on_di_graphs_compiled(graphs)
            await SuiteEventsReceiver.current().on_tests_ready(
                self._queue.tests
            )
            self._completed_test_executions = {}
            context = CURRENT_SUITE_CONTEXT.get()
            config = context.config
            try:
                for step in self._queue.steps:
                    if self.stop_flag:
                        break
                    await self._execute_step(step, suite)
                    if suite.result.stopped_early and config.maxfail:
                        receiver = SuiteEventsReceiver.current()
                        await receiver.on_suite_stopped_early(config.maxfail)
                        break
            finally:
                suite.result.test_executions = [
                    execution
                    for test in self._queue.tests
                    if (
                        execution := self._completed_test_executions.get(
                            test.definition.spec.collection_index
                        )
                    )
                    is not None
                ]

    async def _execute_step(
        self,
        step: _SuiteStep,
        suite: ExecutedSuite,
    ) -> None:
        """Execute one queue step."""
        if step.is_main:
            batch = step.main_batch
            if batch is None:
                return
            for test in batch.tests:
                if self.stop_flag:
                    break
                await self._start_queued_test(test)
                await self._execute_started_test(test, suite)
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
                    await self._start_queued_test(test)

                await self._execute_started_test(test, suite)

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

    async def _start_queued_test(
        self,
        test: ExecutableTest,
    ) -> None:
        module_path = test.definition.spec.locator.module_path
        with ModuleContext(module_path):
            await SuiteEventsReceiver.current().on_test_execution_start(test)

    async def _execute_started_test(
        self,
        test: ExecutableTest,
        suite: ExecutedSuite,
    ) -> None:
        module_path = test.definition.spec.locator.module_path
        with ModuleContext(module_path):
            execution = await test.execute(self.resolver)
        self._record_test_execution(suite, execution)
        closed_module = self._queue.finish(test)
        if closed_module is None:
            return
        with ModuleContext(closed_module):
            await self.resolver.teardown(Scope.MODULE)

    def _record_test_execution(
        self,
        suite: ExecutedSuite,
        execution: ExecutedTest,
    ) -> None:
        self._completed_test_executions[
            execution.definition.spec.collection_index
        ] = execution
        if not execution.result.status.is_failure:
            return
        self._failure_count += 1
        context = CURRENT_SUITE_CONTEXT.get()
        maxfail = context.config.maxfail
        if maxfail and self._failure_count >= maxfail:
            self.stop_flag = True
            suite.result.stopped_early = True
