"""Test runner for executing discovered tests."""

from __future__ import annotations

import asyncio
import re
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from rue.config import Config, load_config
from rue.context.collectors import CURRENT_METRIC_RESULTS
from rue.context.runtime import (
    CURRENT_RUNNER,
    bind,
)
from rue.reports.base import Reporter
from rue.resources import (
    ResourceRegistry,
    ResourceResolver,
    registry as default_resource_registry,
)
from rue.resources.metrics.base import MetricResult
from rue.resources.sut.output import SUTOutputCapture
from rue.storage import SQLiteStore
from rue.telemetry.otel.runtime import otel_runtime
from rue.testing.environment import capture_environment
from rue.testing.execution import DefaultTestFactory
from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.models import (
    Run,
    ExecutedTest,
    LoadedTestDef,
    TestResult,
    TestStatus,
)
from rue.testing.tracing import TestTracer

UUID_STRING_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class Runner:
    """Executes discovered tests with resource injection.

    Args:
        config: Runner configuration values.
        reporters: Optional reporters. Defaults to all registered reporters.

    Examples:
        # Build items with TestSpecCollector + TestLoader, then run.
        # runner = Runner()
        # collection = TestSpecCollector(
        #     include_tags, exclude_tags, keyword
        # ).build_spec_collection(resolved_paths)
        # items = TestLoader(collection.suite_root).load_from_collection(collection)
        # result = await runner.run(items)

        # Concurrent execution with 5 workers (same item preparation as above)
        # runner = Runner(config=Config(concurrency=5))
        # result = await runner.run(items)
    """

    DEFAULT_MAX_CONCURRENCY = 10

    def __init__(
        self,
        *,
        config: Config | None = None,
        reporters: list[Reporter] | None = None,
        fail_fast: bool = False,
        capture_output: bool = True,
        run_id: UUID | str | None = None,
        resource_registry: ResourceRegistry | None = None,
    ) -> None:
        self.config = config or load_config()
        self.fail_fast = fail_fast
        self.capture_output = capture_output
        self._default_run_id = self._normalize_run_id(run_id)
        self.resource_registry = resource_registry or default_resource_registry
        self.reporters = self._resolve_reporters(reporters)
        for reporter in self.reporters:
            reporter.configure(self.config)

        self.semaphore: asyncio.Semaphore | None = None
        self.stop_flag: bool = False

        self.current_run: Run | None = None
        self._store: SQLiteStore | None = None

    def _concurrency_limit(self) -> int:
        return (
            self.config.concurrency
            if self.config.concurrency > 0
            else self.DEFAULT_MAX_CONCURRENCY
        )

    def _db_path(self) -> Path | None:
        return Path(self.config.db_path) if self.config.db_path else None

    def _resolve_reporters(
        self, reporters: list[Reporter] | None
    ) -> list[Reporter]:
        from rue.reports.console import console_reporter  # noqa: F401
        from rue.reports.otel import otel_reporter  # noqa: F401

        if self.config.reporters:
            resolved_reporters: list[Reporter] = []
            for name in self.config.reporters:
                if name not in Reporter.REGISTRY:
                    available = ", ".join(sorted(Reporter.REGISTRY))
                    msg = f"Unknown reporter: {name}. Available: {available}"
                    raise ValueError(msg)
                resolved_reporters.append(Reporter.REGISTRY[name])
            return resolved_reporters
        if reporters is not None:
            return reporters
        return list(Reporter.REGISTRY.values())

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

    async def _notify_trace_collected(
        self, tracer: TestTracer, execution_id: UUID
    ) -> None:
        await asyncio.gather(
            *[
                r.on_trace_collected(tracer, execution_id)
                for r in self.reporters
            ]
        )

    def _ensure_db_ready(self) -> None:
        """Initialize DB and run migrations. Raises MigrationError if not possible."""
        self._store = SQLiteStore(self._db_path())

    @staticmethod
    def _normalize_run_id(run_id: UUID | str | None) -> UUID | None:
        if run_id is None:
            return None
        if isinstance(run_id, UUID):
            return run_id
        if isinstance(run_id, str) and UUID_STRING_PATTERN.fullmatch(run_id):
            return UUID(run_id)
        msg = f"Invalid run_id '{run_id}'. Expected UUID string."
        raise ValueError(msg)

    def _resolve_run_id(self, run_id: UUID | str | None) -> UUID | None:
        normalized_run_id = self._normalize_run_id(run_id)
        if normalized_run_id is not None:
            return normalized_run_id
        return self._default_run_id

    def run_id_exists(self, run_id: UUID | str) -> bool:
        """Return True when run_id already exists in configured SQLite storage."""
        normalized_run_id = self._normalize_run_id(run_id)
        if normalized_run_id is None:
            msg = "run_id cannot be None."
            raise ValueError(msg)
        if self._store is None:
            self._ensure_db_ready()
        return (
            self._store is not None
            and self._store.get_run(normalized_run_id) is not None
        )

    async def run(
        self,
        items: list[LoadedTestDef],
        *,
        run_id: UUID | str | None = None,
    ) -> Run:
        """Run tests and return results.

        Args:
            items: Test definitions to execute (discover via TestSpecCollector and
                TestLoader before calling).
            run_id: Optional UUID for this run. Overrides constructor-level run_id.

        Returns:
            Run with environment, results, and test executions.
        """
        selected_run_id = self._resolve_run_id(run_id)

        if self.config.db_enabled:
            self._ensure_db_ready()
            if selected_run_id and self.run_id_exists(selected_run_id):
                msg = f"run_id '{selected_run_id}' already exists"
                raise ValueError(msg)

        environment = capture_environment()
        if selected_run_id is None:
            self.current_run = Run(environment=environment)
        else:
            self.current_run = Run(
                environment=environment, run_id=selected_run_id
            )

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
            bind(CURRENT_RUNNER, self),
            SUTOutputCapture.sys_capture(swallow=self.capture_output),
            bind(CURRENT_METRIC_RESULTS, metric_results),
        ):
            await self._notify_collection_complete(items, self.current_run)

            resolver = ResourceResolver(self.resource_registry)

            self.semaphore = asyncio.Semaphore(self._concurrency_limit())
            self.stop_flag = False

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

        if self.config.db_enabled and self._store:
            try:
                self._store.save_run(self.current_run)
            except Exception as e:
                warnings.warn(
                    f"Failed to persist run to database: {e}", stacklevel=2
                )

        return self.current_run

    async def _execute_run(
        self,
        *,
        items: list[LoadedTestDef],
        resolver: ResourceResolver,
        run: Run,
    ) -> None:
        """Execute the test run with the given items and resolver."""
        self._factory = DefaultTestFactory(
            config=self.config,
            run_id=run.run_id,
            semaphore=self.semaphore,
            is_stopped=lambda: self.stop_flag,
            on_complete=self._on_execution_complete,
            on_trace_collected=self._notify_trace_collected,
        )
        self._built_tests: dict[int, ExecutableTest] = {}
        for item in items:
            if not item.spec.definition_error:
                self._built_tests[id(item)] = self._factory.build(item)
        await self._notify_tests_ready(list(self._built_tests.values()))
        try:
            if self._concurrency_limit() == 1:
                await self._run_sequential(items, resolver, run)
            else:
                await self._run_concurrent(items, resolver, run)
        finally:
            await resolver.teardown()

    async def _execute_item(
        self, item: LoadedTestDef, resolver: ResourceResolver
    ) -> ExecutedTest:
        """Execute a single test with error handling."""
        if item.spec.definition_error:
            execution = ExecutedTest(
                definition=item,
                result=TestResult(
                    status=TestStatus.ERROR,
                    duration_ms=0,
                    error=ValueError(item.spec.definition_error),
                ),
                execution_id=uuid4(),
            )
            await self._on_execution_complete(execution)
            return execution

        test = self._built_tests[id(item)]
        t_start = time.perf_counter()

        try:
            execution = await test.execute(resolver)
        except Exception as e:
            duration = (time.perf_counter() - t_start) * 1000
            execution = ExecutedTest(
                definition=item,
                result=TestResult(
                    status=TestStatus.ERROR, duration_ms=duration, error=e
                ),
                execution_id=uuid4(),
            )
            await self._on_execution_complete(execution)
            return execution

        return execution

    async def _run_sequential(
        self, items: list[LoadedTestDef], resolver: ResourceResolver, run: Run
    ) -> None:
        """Run tests sequentially."""
        failures = 0

        for item in items:
            if self.stop_flag:
                break
            await self._notify_test_start(item)
            execution = await self._execute_item(item, resolver)
            run.result.executions.append(execution)

            if execution.result.status.is_failure:
                failures += 1
                if self.config.maxfail and failures >= self.config.maxfail:
                    run.result.stopped_early = True
                    self.stop_flag = True
                    await self._notify_run_stopped_early(self.config.maxfail)
                    break

    async def _run_concurrent(
        self, items: list[LoadedTestDef], resolver: ResourceResolver, run: Run
    ) -> None:
        """Run tests concurrently."""
        state_lock = asyncio.Lock()
        failures = 0
        results: list[ExecutedTest | None] = [None] * len(items)

        async def run_one(idx: int, item: LoadedTestDef) -> None:
            nonlocal failures

            async with state_lock:
                if self.stop_flag:
                    return

            await self._notify_test_start(item)
            execution = await self._execute_item(item, resolver)

            async with state_lock:
                results[idx] = execution
                if execution.result.status.is_failure:
                    failures += 1
                    if self.config.maxfail and failures >= self.config.maxfail:
                        self.stop_flag = True
                        run.result.stopped_early = True

        task_results = await asyncio.gather(
            *[run_one(i, item) for i, item in enumerate(items)],
            return_exceptions=True,
        )

        task_errors = [
            result for result in task_results if isinstance(result, Exception)
        ]
        if task_errors:
            if len(task_errors) == 1:
                raise task_errors[0]
            raise ExceptionGroup(
                "Concurrent test callbacks failed", task_errors
            )

        for execution in results:
            if execution is not None:
                run.result.executions.append(execution)

        if run.result.stopped_early and self.config.maxfail:
            await self._notify_run_stopped_early(self.config.maxfail)
