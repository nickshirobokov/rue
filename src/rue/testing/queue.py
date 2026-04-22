"""Execution queue for runner-owned test scheduling."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.types import ExecutionBackend


@dataclass(slots=True)
class QueueEntry:
    """One top-level test in queue order."""

    index: int
    test: ExecutableTest


@dataclass(slots=True)
class RunnerStep:
    """One sequential or parallel runner step."""

    backend: ExecutionBackend | None = None
    entries: list[QueueEntry] = field(default_factory=list)
    _next_index: int = field(default=0, init=False, repr=False)
    _active_count: int = field(default=0, init=False, repr=False)

    @property
    def tests(self) -> list[ExecutableTest]:
        return [entry.test for entry in self.entries]

    @property
    def is_main(self) -> bool:
        return self.backend is ExecutionBackend.MAIN

    @property
    def is_module_main(self) -> bool:
        return self.backend is ExecutionBackend.MODULE_MAIN

    @property
    def is_parallel(self) -> bool:
        return self.backend is None

    @property
    def first_index(self) -> int:
        return self.entries[0].index

    def append(self, test: ExecutableTest, index: int) -> None:
        """Append a test to this step."""
        self.entries.append(QueueEntry(index=index, test=test))

    def has_pending(self) -> bool:
        return self._next_index < len(self.entries)

    def has_active(self) -> bool:
        return self._active_count > 0

    def is_complete(self) -> bool:
        return not self.has_pending() and not self.has_active()

    def can_start(self) -> bool:
        return self.has_pending() and (self.is_parallel or not self.has_active())

    def start_next(self) -> QueueEntry:
        entry = self.entries[self._next_index]
        self._next_index += 1
        self._active_count += 1
        return entry

    def finish(self) -> None:
        self._active_count -= 1


@dataclass(slots=True)
class ModuleQueue:
    """Step queue for a single module inside one concurrent segment."""

    module_path: Path
    steps: list[RunnerStep] = field(default_factory=list)
    _next_step_index: int = field(default=0, init=False, repr=False)

    @property
    def current_step(self) -> RunnerStep | None:
        if self._next_step_index >= len(self.steps):
            return None
        return self.steps[self._next_step_index]

    @property
    def first_index(self) -> int:
        return self.steps[0].first_index

    def append(self, test: ExecutableTest, index: int) -> None:
        backend = (
            ExecutionBackend.MODULE_MAIN
            if test.backend is ExecutionBackend.MODULE_MAIN
            else None
        )
        if self.steps and self.steps[-1].backend is backend:
            self.steps[-1].append(test, index)
            return
        step = RunnerStep(backend=backend)
        step.append(test, index)
        self.steps.append(step)

    def advance(self) -> None:
        while True:
            step = self.current_step
            if step is None or not step.is_complete():
                return
            self._next_step_index += 1

    def has_work(self) -> bool:
        return self.current_step is not None


@dataclass(slots=True)
class QueueSegment:
    """One absolute queue segment."""

    main_step: RunnerStep | None = None
    module_queues: list[ModuleQueue] = field(default_factory=list)
    _module_index: dict[Path, ModuleQueue] = field(
        default_factory=dict, init=False, repr=False
    )
    _next_module_index: int = field(default=0, init=False, repr=False)

    @property
    def is_main(self) -> bool:
        return self.main_step is not None

    @property
    def tests(self) -> list[ExecutableTest]:
        if self.main_step is not None:
            return self.main_step.tests
        return [
            test
            for queue in self.module_queues
            for step in queue.steps
            for test in step.tests
        ]

    @property
    def total_tests(self) -> int:
        return len(self.tests)

    def add(self, test: ExecutableTest, index: int) -> None:
        if test.backend is ExecutionBackend.MAIN:
            if self.main_step is None:
                self.main_step = RunnerStep(backend=ExecutionBackend.MAIN)
            self.main_step.append(test, index)
            return

        module_path = test.definition.spec.module_path
        queue = self._module_index.get(module_path)
        if queue is None:
            queue = ModuleQueue(module_path=module_path)
            self._module_index[module_path] = queue
            self.module_queues.append(queue)
        queue.append(test, index)

    def dequeue_ready(
        self,
    ) -> tuple[ModuleQueue, RunnerStep, QueueEntry] | None:
        count = len(self.module_queues)
        for offset in range(count):
            queue_index = (self._next_module_index + offset) % count
            queue = self.module_queues[queue_index]
            queue.advance()
            step = queue.current_step
            if step is None or not step.can_start():
                continue
            entry = step.start_next()
            self._next_module_index = (queue_index + 1) % count
            return queue, step, entry
        return None

    def finish(self, queue: ModuleQueue, step: RunnerStep) -> None:
        step.finish()
        queue.advance()

    def is_complete(self) -> bool:
        return all(not queue.has_work() for queue in self.module_queues)


@dataclass(slots=True)
class TestQueue:
    """Ordered queue of backend-aware runner segments."""

    segments: list[QueueSegment] = field(default_factory=list)
    _tests: list[ExecutableTest] = field(
        default_factory=list, init=False, repr=False
    )
    _next_index: int = field(default=0, init=False, repr=False)

    def add(self, test: ExecutableTest) -> None:
        """Append a top-level executable test to the queue."""
        index = self._next_index
        self._next_index += 1
        self._tests.append(test)
        segment = (
            self._main_segment()
            if test.backend is ExecutionBackend.MAIN
            else self._concurrent_segment()
        )
        segment.add(test, index)

    def _main_segment(self) -> QueueSegment:
        if self.segments and self.segments[-1].is_main:
            return self.segments[-1]
        segment = QueueSegment(main_step=RunnerStep(backend=ExecutionBackend.MAIN))
        self.segments.append(segment)
        return segment

    def _concurrent_segment(self) -> QueueSegment:
        if self.segments and not self.segments[-1].is_main:
            return self.segments[-1]
        segment = QueueSegment()
        self.segments.append(segment)
        return segment

    @property
    def tests(self) -> list[ExecutableTest]:
        """Flattened top-level executable tests in queue order."""
        return self._tests.copy()

    @property
    def steps(self) -> list[RunnerStep]:
        """Flattened runner steps ordered by discovery index."""
        steps: list[RunnerStep] = []
        for segment in self.segments:
            if segment.main_step is not None:
                steps.append(segment.main_step)
                continue
            steps.extend(
                sorted(
                    (
                        step
                        for queue in segment.module_queues
                        for step in queue.steps
                    ),
                    key=lambda step: step.first_index,
                )
            )
        return steps
