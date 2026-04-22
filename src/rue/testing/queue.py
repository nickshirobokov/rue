"""Execution queue for runner-owned test scheduling."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.types import ExecutionBackend


@dataclass(slots=True)
class QueueBatch:
    """One sequential or parallel batch of tests."""

    backend: ExecutionBackend | None = None
    tests: list[ExecutableTest] = field(default_factory=list)
    _next_index: int = field(default=0, init=False, repr=False)
    _active_count: int = field(default=0, init=False, repr=False)

    @property
    def is_main(self) -> bool:
        return self.backend is ExecutionBackend.MAIN

    @property
    def is_parallel(self) -> bool:
        return self.backend is None

    @property
    def has_pending(self) -> bool:
        return self._next_index < len(self.tests)

    @property
    def has_active(self) -> bool:
        return self._active_count > 0

    @property
    def is_complete(self) -> bool:
        return not self.has_pending and not self.has_active

    @property
    def can_start(self) -> bool:
        return self.has_pending and (self.is_parallel or not self.has_active)

    def append(self, test: ExecutableTest) -> None:
        """Append a test to this batch."""
        self.tests.append(test)

    def start_next(self) -> ExecutableTest:
        test = self.tests[self._next_index]
        self._next_index += 1
        self._active_count += 1
        return test

    def finish(self) -> None:
        self._active_count -= 1


@dataclass(slots=True)
class ModuleQueue:
    """Batch queue for a single module inside one concurrent runner step."""

    module_path: Path
    batches: list[QueueBatch] = field(default_factory=list)
    _next_batch_index: int = field(default=0, init=False, repr=False)

    @property
    def current_batch(self) -> QueueBatch | None:
        if self._next_batch_index >= len(self.batches):
            return None
        return self.batches[self._next_batch_index]

    @property
    def has_work(self) -> bool:
        return self.current_batch is not None

    def append(self, test: ExecutableTest) -> None:
        backend = (
            ExecutionBackend.MODULE_MAIN
            if test.backend is ExecutionBackend.MODULE_MAIN
            else None
        )
        if self.batches and self.batches[-1].backend is backend:
            self.batches[-1].append(test)
            return
        batch = QueueBatch(backend=backend)
        batch.append(test)
        self.batches.append(batch)

    def advance(self) -> None:
        while True:
            batch = self.current_batch
            if batch is None or not batch.is_complete:
                return
            self._next_batch_index += 1


@dataclass(slots=True)
class RunnerStep:
    """One absolute runner step (main or parallel module region)."""

    main_batch: QueueBatch | None = None
    module_queues: list[ModuleQueue] = field(default_factory=list)
    _module_index: dict[Path, ModuleQueue] = field(
        default_factory=dict, init=False, repr=False
    )
    _next_module_index: int = field(default=0, init=False, repr=False)

    @property
    def is_main(self) -> bool:
        return self.main_batch is not None

    @property
    def total_tests_count(self) -> int:
        main = self.main_batch
        if main is not None:
            return len(main.tests)
        return sum(
            len(batch.tests)
            for mq in self.module_queues
            for batch in mq.batches
        )

    @property
    def is_complete(self) -> bool:
        return all(not mq.has_work for mq in self.module_queues)

    def add(self, test: ExecutableTest) -> None:
        if test.backend is ExecutionBackend.MAIN:
            if self.main_batch is None:
                self.main_batch = QueueBatch(backend=ExecutionBackend.MAIN)
            self.main_batch.append(test)
            return

        module_path = test.definition.spec.module_path
        mq = self._module_index.get(module_path)
        if mq is None:
            mq = ModuleQueue(module_path=module_path)
            self._module_index[module_path] = mq
            self.module_queues.append(mq)
        mq.append(test)

    def dequeue_ready(
        self,
    ) -> tuple[ModuleQueue, QueueBatch, ExecutableTest] | None:
        count = len(self.module_queues)
        for offset in range(count):
            queue_index = (self._next_module_index + offset) % count
            mq = self.module_queues[queue_index]
            mq.advance()
            batch = mq.current_batch
            if batch is None or not batch.can_start:
                continue
            entry = batch.start_next()
            self._next_module_index = (queue_index + 1) % count
            return mq, batch, entry
        return None

    def finish(self, mq: ModuleQueue, batch: QueueBatch) -> None:
        batch.finish()
        mq.advance()


@dataclass(slots=True)
class SessionQueue:
    """Ordered queue of backend-aware runner steps."""

    steps: list[RunnerStep] = field(default_factory=list)
    _tests: list[ExecutableTest] = field(
        default_factory=list, init=False, repr=False
    )

    def add(self, test: ExecutableTest) -> None:
        """Append a top-level executable test to the queue."""
        self._tests.append(test)
        match test.backend:
            case ExecutionBackend.MAIN:
                if self.steps and self.steps[-1].is_main:
                    runner_step = self.steps[-1]
                else:
                    runner_step = RunnerStep(
                        main_batch=QueueBatch(backend=ExecutionBackend.MAIN)
                    )
                    self.steps.append(runner_step)
            case _:
                if self.steps and not self.steps[-1].is_main:
                    runner_step = self.steps[-1]
                else:
                    runner_step = RunnerStep()
                    self.steps.append(runner_step)
        runner_step.add(test)

    @property
    def tests(self) -> list[ExecutableTest]:
        """Flattened top-level executable tests in queue order."""
        return sorted(
            self._tests,
            key=lambda test: test.definition.spec.collection_index,
        )

    @property
    def batches(self) -> list[QueueBatch]:
        """Flattened queue batches ordered by discovery index."""
        out: list[QueueBatch] = []
        for step in self.steps:
            if step.main_batch is not None:
                out.append(step.main_batch)
                continue
            out.extend(
                sorted(
                    (
                        batch
                        for mq in step.module_queues
                        for batch in mq.batches
                    ),
                    key=lambda batch: batch.tests[0].definition.spec.collection_index,
                )
            )
        return out
