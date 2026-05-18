"""Environment handle and context-routed activation."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Mapping, MutableMapping, Sequence
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import ClassVar

from rue.context.scopes import Scope
from rue.environment.checkpoint import Checkpoint, CheckpointDelta
from rue.environment.sources import Source
from rue.environment.storage import (
    EnvironmentStorage,
    clone_tree,
    empty_tree,
)
from rue.environment.sync import EnvironmentSyncState
from rue.environment.var import EnvVars


_ACTIVE_ENVIRONMENTS: ContextVar[tuple[Environment, ...]] = ContextVar(
    "environment_stack", default=()
)


class Environment:
    """Per-scope filesystem + env-var sandbox handle.

    Implements the ``SyncableResource[EnvironmentSyncState]`` protocol
    structurally; the ABC subclass relationship is established lazily by
    ``rue.resources.builtins`` to break a module-load cycle with
    ``rue.resources``.

    Each instance knows the scope owner for its filesystem root.
    """

    _real_environ: ClassVar[MutableMapping[str, str]] = os.environ
    _real_environb: ClassVar[MutableMapping[bytes, bytes] | None] = getattr(
        os, "environb", None
    )

    __slots__ = (
        "_cache_path",
        "_cwd",
        "_root",
        "_scope",
        "_vars",
    )

    def __init__(self, *, root: Path, scope: Scope) -> None:
        self._root = root.resolve()
        self._cache_path: Path | None = None
        self._scope = scope
        self._cwd = self._root
        self._vars = EnvVars()

    @property
    def root(self) -> Path:
        """Sandbox root."""
        return self._root

    @property
    def cwd(self) -> Path:
        """Current default working directory inside the sandbox."""
        return self._cwd

    @cwd.setter
    def cwd(self, target: Path) -> None:
        if target != self._root and not target.is_relative_to(self._root):
            msg = (
                f"chdir target escapes environment root: "
                f"{target} is not inside {self._root}"
            )
            raise ValueError(msg)
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        self._cwd = target

    @property
    def vars(self) -> EnvVars:
        """Environment variable overlay."""
        return self._vars

    @property
    def scope(self) -> Scope:
        """The scope that owns this environment."""
        return self._scope

    # file system state analysis

    def get_checkpoint(self) -> Checkpoint:
        """Return a filesystem checkpoint without mutating environment state."""
        return Checkpoint.from_root(self._root, self._cache_path)

    def get_diff(self, baseline: Checkpoint | None = None) -> CheckpointDelta:
        """Return a diff from ``baseline`` to the current sandbox state.

        When ``baseline`` is omitted, the diff is taken against the loaded
        source's cache (set by the most recent ``load()`` call); if no source
        has been loaded the baseline is empty, so every file currently under
        the sandbox root appears as ``added``.
        """
        if baseline is None:
            baseline = Checkpoint(
                baseline=self._cache_path, updated_paths=()
            )
        return baseline.compare(self.get_checkpoint())

    # file system state manipulation

    def path(self, p: str | Path = ".") -> Path:
        """Resolve `p` against the sandbox root and reject escapes."""
        candidate = (self._root / Path(p)).resolve()
        root = self._root
        if candidate != root and not candidate.is_relative_to(root):
            msg = (
                f"Path '{p}' resolves outside the environment root: "
                f"{candidate} is not inside {root}."
            )
            raise ValueError(msg)
        return candidate

    def chdir(self, p: str | Path = ".") -> None:
        """Set the default cwd to a sandboxed location."""
        self.cwd = self.path(p)

    def reset(self) -> None:
        """Restore the sandbox from its cached baseline and reset the cwd."""
        empty_tree(self._root)
        if self._cache_path is not None:
            for child in self._cache_path.iterdir():
                clone_tree(child, self._root / child.name)
        self.cwd = self._root

    # execution inside the environment

    async def exec(
        self,
        cmd: Sequence[str | Path],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        input: bytes | str | None = None,  # noqa: A002 - mirrors subprocess
        check: bool = False,
        timeout: float | None = None,
        inherit_os: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run `cmd` rooted at this environment.

        cwd defaults to `self.cwd` and is validated to live under root. The
        env merge order is `os.environ if inherit_os else {}` -> drop hidden
        keys -> apply overrides -> apply caller `env` on top.
        """
        target_cwd = self.path(cwd) if cwd is not None else self._cwd
        if not target_cwd.is_dir():
            msg = f"exec cwd is not a directory: {target_cwd}"
            raise NotADirectoryError(msg)

        base = dict(type(self)._real_environ) if inherit_os else {}
        merged_env = dict(self._vars.view(base))
        if env:
            merged_env.update(env)

        if isinstance(input, str):
            stdin_bytes: bytes | None = input.encode("utf-8")
        else:
            stdin_bytes = input

        process = await asyncio.create_subprocess_exec(
            *(str(arg) for arg in cmd),
            cwd=str(target_cwd),
            env=merged_env,
            stdin=(subprocess.PIPE if stdin_bytes is not None else None),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            if timeout is None:
                stdout, stderr = await process.communicate(input=stdin_bytes)
            else:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=stdin_bytes),
                    timeout=timeout,
                )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        completed: subprocess.CompletedProcess[bytes] = (
            subprocess.CompletedProcess(
                args=list(cmd),
                returncode=process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
            )
        )
        if check:
            completed.check_returncode()
        return completed

    def __enter__(self) -> Environment:
        """Bind this env as the active routing target for the current context.

        Activation is context-local: nested and concurrent ``with`` blocks
        each push an entry onto a per-context stack. The chokepoint
        dispatchers (``os.environ``, ``os.getcwd``, ``open``, ...) read
        from this binding to route per-test instead of mutating shared
        process state.
        """
        _ACTIVE_ENVIRONMENTS.set((*_ACTIVE_ENVIRONMENTS.get(), self))
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Pop this env from the per-context activation stack."""
        stack = _ACTIVE_ENVIRONMENTS.get()
        if not stack:
            raise RuntimeError("No active Environment to deactivate.")
        if stack[-1] is not self:
            raise RuntimeError("Cannot deactivate Environment out of order.")
        _ACTIVE_ENVIRONMENTS.set(stack[:-1])

    # environment state management

    async def load(self, source: Source) -> None:
        """Materialize `source` into the sandbox and reset the cwd."""
        storage = EnvironmentStorage()
        self._cache_path = await source.materialize(
            cache_root=storage.cache_dir,
            dst=self._root,
        )
        self.cwd = self._root

    @classmethod
    def current(cls) -> Environment | None:
        """Return the innermost activated Environment in this context."""
        stack = _ACTIVE_ENVIRONMENTS.get()
        return stack[-1] if stack else None

    # resource transport serialization (see resources.sync)

    def get_sync_state(self) -> EnvironmentSyncState:
        """Return object state safe for subprocess transport."""
        relative_cwd = PurePosixPath(
            self._cwd.resolve().relative_to(self._root).as_posix() or "."
        )
        return EnvironmentSyncState(
            root=self._root,
            overrides=dict(self._vars.overrides),
            hidden=frozenset(self._vars.hidden),
            cwd=relative_cwd,
        )

    def from_sync_state(self, state: EnvironmentSyncState) -> None:
        """Hydrate this env from subprocess-safe object state."""
        self._root = state.root.resolve()
        self._vars = EnvVars()
        for key, value in state.overrides.items():
            self._vars[key] = value
        for key in state.hidden:
            self._vars.unset(key)
        target_cwd = (self._root / Path(state.cwd)).resolve()
        if not target_cwd.is_relative_to(self._root):
            target_cwd = self._root
        self.cwd = target_cwd

    def merge_sync_states(
        self,
        baseline: EnvironmentSyncState,
        update: EnvironmentSyncState,
    ) -> None:
        """Apply worker-emitted object state back into the parent env."""
        del baseline
        self._root = update.root.resolve()
        target_cwd = (self._root / Path(update.cwd)).resolve()
        if not target_cwd.is_relative_to(self._root):
            target_cwd = self._root
        self.cwd = target_cwd
        self._vars = EnvVars()
        for key, value in update.overrides.items():
            self._vars[key] = value
        for key in update.hidden:
            self._vars.unset(key)

__all__ = [
    "Environment",
]
