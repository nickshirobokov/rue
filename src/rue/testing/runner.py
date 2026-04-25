"""Test runner for executing discovered tests."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from uuid import UUID

from rue.config import Config
from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.process_pool import process_pool_scope
from rue.context.runtime import bind
from rue.experiments.models import ExperimentVariant
from rue.reports.base import Reporter
from rue.resources import (
    ResourceResolver,
    registry as default_resource_registry,
)
from rue.resources.metrics.base import MetricResult
from rue.resources.sut.output import SUTOutputCapture
from rue.storage import Store
from rue.telemetry.otel.runtime import otel_runtime
from rue.testing.execution import DefaultTestFactory
from rue.testing.execution.queue import RunnerStep, SessionQueue
from rue.testing.models import (
    ExecutedTest,
    LoadedTestDef,
    Run,
    RunEnvironment,
)
from rue.testing.models.spec import SetupFileRef


class Runner:
    """Executes discovered tests with resource injection.

    Args:
        config: Runner configuration values.
        reporters: Reporter instances for lifecycle notifications.
        store: Optional persistence backend for completed runs.
    """

    DEFAULT_MAX_CONCURRENCY = 10

    def __init__(
        self,
        *,
        config: Config,
        reporters: list[Reporter],
        store: Store | None = None,
        fail_fast: bool = False,
        capture_output: bool = True,
        experiment_variant: ExperimentVariant | None = None,
        experiment_setup_chain: tuple[SetupFileRef, ...] = (),
    ) -> None:
        self.config = config
        self.fail_fast = fail_fast
        self.capture_output = capture_output
        self.reporters = reporters
        self.store = store
        self.experiment_variant = experiment_variant
        self.experiment_setup_chain = experiment_setup_chain
        for reporter in self.reporters:
            reporter.configure(self.config)

        self.semaphore: asyncio.Semaphore | None = None
        self.stop_flag: bool = False
        self._failure_count: int = 0
        self._queue = SessionQueue()
        self._completed_executions: dict[int, ExecutedTest] = {}

        self.current_run: Run | None = None

    def _concurrency_limit(self) -> int:
        return (
            self.config.concurrency
            if self.config.concurrency > 0
            else self.DEFAULT_MAX_CONCURRENCY
        )

    async def _notify_no_tests_found(self) -> None:
        await asyncio.gather(*[r.on_no_tests_found() for r in self.reporters])

    async def _notify_collection_complete(
        self, items: list[LoadedTestDef], run: Run
    ) -> None:
        await asyncio.gather(
            *[r.on_collection_complete(items, run) for r in self.reporters]
        )

    async def _notify_test_start(self, item: LoadedTestDef) -> None:
        await asyncio.gather(*[r.on_test_start(item) for r in self.reporters])

    async def _on_execution_complete(self, execution: ExecutedTest) -> None:
        await asyncio.gather(
            *[r.on_execution_complete(execution) for r in self.reporters]
        )

    async def _notify_run_complete(self, run: Run) -> None:
        await asyncio.gather(*[r.on_run_complete(run) for r in self.reporters])

    async def _notify_tests_ready(self, tests: list) -> None:
        await asyncio.gather(*[r.on_tests_ready(tests) for r in self.reporters])

    async def _notify_run_stopped_early(self, failure_count: int) -> None:
        await asyncio.gather(
            *[r.on_run_stopped_early(failure_count) for r in self.reporters]
        )

    async def run(
        self,
        items: list[LoadedTestDef],
        *,
        run_id: UUID | None = None,
    ) -> Run:
        """Run tests and return results.

        Args:
            items: Test definitions to execute. Discover them with
                TestSpecCollector and TestLoader before calling.
            run_id: Optional UUID for this run.

        Returns:
            Run with environment, results, and test executions.
        """
        environment = RunEnvironment.build_from_current()
        if run_id is None:
            self.current_run = Run(environment=environment)
        else:
            self.current_run = Run(environment=environment, run_id=run_id)

        if self.config.otel:
            otel_runtime.configure()

        if not items:
            await self._notify_no_tests_found()
            self.current_run.end_time = datetime.now(UTC)
            return self.current_run

        if self.fail_fast:
            for item in items:
                item.fail_fast = True

        metric_results: list[MetricResult] = []
        start = time.perf_counter()

        with (
            SUTOutputCapture.sys_capture(swallow=self.capture_output),
            bind(CURRENT_METRIC_RESULTS, metric_results),
        ):
            await self._notify_collection_complete(items, self.current_run)

            resolver = ResourceResolver(default_resource_registry)

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
                if self.config.timeout is not None:
                    await asyncio.wait_for(
                        run_task, timeout=self.config.timeout
                    )
                else:
                    await run_task
            except TimeoutError:
                self.current_run.result.stopped_early = True
                self.stop_flag = True

        self.current_run.result.total_duration_ms = (
            time.perf_counter() - start
        ) * 1000
        self.current_run.result.metric_results = metric_results.copy()
        self.current_run.end_time = datetime.now(UTC)

        await self._notify_run_complete(self.current_run)

        if self.store is not None:
            self.store.save_run(self.current_run)

        return self.current_run

    async def _execute_run(
        self,
        *,
        items: list[LoadedTestDef],
        resolver: ResourceResolver,
        run: Run,
    ) -> None:
        """Execute the test run with the given items and resolver."""
        with process_pool_scope(self._concurrency_limit()):
            self._queue = SessionQueue()
            self._factory = DefaultTestFactory(
                config=self.config,
                run_id=run.run_id,
                semaphore=self.semaphore,
                is_stopped=lambda: self.stop_flag,
                on_complete=self._on_execution_complete,
                queue=self._queue,
                experiment_variant=self.experiment_variant,
                experiment_setup_chain=self.experiment_setup_chain,
            )
            for item in items:
                self._factory.build(item)
            await self._notify_tests_ready(self._queue.tests)
            self._completed_executions = {}
            try:
                for step in self._queue.steps:
                    if self.stop_flag:
                        break
                    await self._run_step(step, resolver, run)
                    if run.result.stopped_early and self.config.maxfail:
                        await self._notify_run_stopped_early(
                            self.config.maxfail
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
                await resolver.teardown()

    async def _run_step(
        self,
        step: RunnerStep,
        resolver: ResourceResolver,
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
                await self._notify_test_start(test.definition)
                execution = await test.execute(resolver)
                self._record_execution(run, execution)
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
                    await self._notify_test_start(test.definition)

                execution = await test.execute(resolver)
                self._record_execution(run, execution)

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
        if self.config.maxfail and self._failure_count >= self.config.maxfail:
            self.stop_flag = True
            run.result.stopped_early = True
