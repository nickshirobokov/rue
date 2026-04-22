"""Execution queue for runner-owned test scheduling."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field

from rue.testing.execution.interfaces import ExecutableTest
from rue.testing.execution.types import ExecutionBackend


@dataclass(slots=True)
class RunnerStep:
    """One sequential or parallel runner step."""

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

    def append(self, test: ExecutableTest) -> None:
        """Append a test to this step."""
        self.tests.append(test)

    def has_pending(self) -> bool:
        return self._next_index < len(self.tests)

    def has_active(self) -> bool:
        return self._active_count > 0

    def is_complete(self) -> bool:
        return not self.has_pending() and not self.has_active()

    def can_start(self) -> bool:
        return self.has_pending() and (self.is_parallel or not self.has_active())

    def start_next(self) -> ExecutableTest:
        test = self.tests[self._next_index]
        self._next_index += 1
        self._active_count += 1
        return test

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

    def append(self, test: ExecutableTest) -> None:
        backend = (
            ExecutionBackend.MODULE_MAIN
            if test.backend is ExecutionBackend.MODULE_MAIN
            else None
        )
        if self.steps and self.steps[-1].backend is backend:
            self.steps[-1].append(test)
            return
        step = RunnerStep(backend=backend)
        step.append(test)
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

    def add(self, test: ExecutableTest) -> None:
        if test.backend is ExecutionBackend.MAIN:
            if self.main_step is None:
                self.main_step = RunnerStep(backend=ExecutionBackend.MAIN)
            self.main_step.append(test)
            return

        module_path = test.definition.spec.module_path
        queue = self._module_index.get(module_path)
        if queue is None:
            queue = ModuleQueue(module_path=module_path)
            self._module_index[module_path] = queue
            self.module_queues.append(queue)
        queue.append(test)

    def dequeue_ready(
        self,
    ) -> tuple[ModuleQueue, RunnerStep, ExecutableTest] | None:
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

    def add(self, test: ExecutableTest) -> None:
        """Append a top-level executable test to the queue."""
        self._tests.append(test)
        match test.backend:
            case ExecutionBackend.MAIN:
                if self.segments and self.segments[-1].is_main:
                    segment = self.segments[-1]
                else:
                    segment = QueueSegment(
                        main_step=RunnerStep(backend=ExecutionBackend.MAIN)
                    )
                    self.segments.append(segment)
            case _:
                if self.segments and not self.segments[-1].is_main:
                    segment = self.segments[-1]
                else:
                    segment = QueueSegment()
                    self.segments.append(segment)
        segment.add(test)

    @property
    def tests(self) -> list[ExecutableTest]:
        """Flattened top-level executable tests in queue order."""
        return sorted(
            self._tests,
            key=lambda test: test.definition.spec.collection_index,
        )

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
                    key=lambda step: step.tests[0].definition.spec.collection_index,
                )
            )
        return steps
