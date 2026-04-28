"""Runtime context variables for Rue execution."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from importlib.metadata import distributions
from types import TracebackType
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from rue.config import Config
from rue.models import Spec


if TYPE_CHECKING:
    from rue.resources.models import ResourceSpec
    from rue.resources.resolver import ResourceResolver
    from rue.testing.models.loaded import LoadedTestDef
    from rue.testing.tracing import TestTracer


@dataclass(slots=True)
class TestContext:
    """Runtime data owned by one executing test."""

    __test__ = False

    item: LoadedTestDef
    execution_id: UUID
    _tokens: list[Token[TestContext]] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    def __enter__(self) -> TestContext:
        """Bind this test context to the current execution scope."""
        self._tokens.append(CURRENT_TEST.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous test context."""
        CURRENT_TEST.reset(self._tokens.pop())


@dataclass(slots=True)
class ResourceTransactionContext:
    """Runtime data owned by one resource resolution transaction."""

    consumer_spec: Spec
    provider_spec: Spec
    resolver: ResourceResolver
    direct_dependencies: tuple[ResourceSpec, ...] = ()
    _tokens: list[Token[ResourceTransactionContext]] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    def __enter__(self) -> ResourceTransactionContext:
        """Bind this transaction to the current resolution scope."""
        self._tokens.append(CURRENT_RESOURCE_TRANSACTION.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous resource transaction."""
        CURRENT_RESOURCE_TRANSACTION.reset(self._tokens.pop())


class RunEnvironment(BaseModel):
    """Metadata about the environment where tests were executed."""

    commit_hash: str | None = None
    branch: str | None = None
    dirty: bool | None = None

    python_version: str
    platform: str
    hostname: str
    working_directory: str
    rue_version: str

    @classmethod
    def build_from_current(cls) -> RunEnvironment:
        """Build environment metadata from the current process."""
        commit_hash = None
        branch = None
        dirty = None
        if shutil.which("git") is not None:
            in_repo = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                check=False,
                text=True,
            )
            if in_repo.returncode == 0:
                commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                current_branch = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                if commit.returncode == 0:
                    commit_hash = commit.stdout.strip() or None
                if current_branch.returncode == 0:
                    branch = current_branch.stdout.strip() or None
                if status.returncode == 0:
                    dirty = bool(status.stdout.strip())

        return cls(
            commit_hash=commit_hash,
            branch=branch,
            dirty=dirty,
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            hostname=socket.gethostname(),
            working_directory=os.getcwd(),
            rue_version=next(
                (dist.version for dist in distributions(name="rue")),
                "0.0.0",
            ),
        )


class RunContext(BaseModel):
    """Read-only data resolved before executing one run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    config: Config = Field(default_factory=Config)
    run_id: UUID = Field(default_factory=uuid4)
    environment: RunEnvironment = Field(
        default_factory=RunEnvironment.build_from_current
    )
    experiment_variant: Any | None = None
    experiment_setup_chain: tuple[Any, ...] = ()
    _tokens: list[Token[RunContext]] = PrivateAttr(default_factory=list)

    def __enter__(self) -> RunContext:
        """Bind this run context to the current execution scope."""
        self._tokens.append(CURRENT_RUN_CONTEXT.set(self))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the previous run context."""
        CURRENT_RUN_CONTEXT.reset(self._tokens.pop())

    def __getstate__(self) -> dict[str, Any]:
        """Serialize run data without process-local contextvar tokens."""
        state = super().__getstate__()
        state["__pydantic_private__"] = {"_tokens": []}
        return state


CURRENT_TEST: ContextVar[TestContext] = ContextVar("current_test")
CURRENT_RUN_CONTEXT: ContextVar[RunContext] = ContextVar(
    "current_run_context"
)
CURRENT_TEST_TRACER: ContextVar[TestTracer | None] = ContextVar(
    "current_test_tracer", default=None
)
CURRENT_SUT_SPAN_IDS: ContextVar[tuple[int, ...]] = ContextVar(
    "current_sut_span_ids", default=()
)
CURRENT_RESOURCE_TRANSACTION: ContextVar[
    ResourceTransactionContext
] = ContextVar(
    "current_resource_transaction",
)


@contextmanager
def bind[T](var: ContextVar[T], value: T) -> Iterator[None]:
    """Bind a context variable for a scoped block."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)
