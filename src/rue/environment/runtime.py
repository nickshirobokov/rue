"""Environment handle, env-var overlay, and process activation."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from rue.context.scopes import Scope
from rue.environment.checkpoint import Checkpoint, Diff
from rue.environment.sources import Source
from rue.environment.storage import (
    EnvironmentStorage,
    clone_tree,
    empty_tree,
)
from rue.environment.sync import (
    EnvironmentSyncState,
    FileDelta,
    FileDeltaKind,
)


if TYPE_CHECKING:
    from rue.resources.models import ResourceSpec


_ACTIVATION_LOCK = threading.Lock()
_ACTIVE_ENVIRONMENT: Environment | None = None


class EnvironmentVars(MutableMapping[str, str]):
    """Override layer over `os.environ` for an `Environment`.

    Stores user-supplied overrides and a set of "hidden" keys to mask.
    `merged(base)` returns the effective mapping you'd see by composing the
    overlay onto an arbitrary base, used by `Environment.exec` and during
    activation.
    """

    __slots__ = ("_hidden", "_overrides")

    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}
        self._hidden: set[str] = set()

    def __getitem__(self, key: str) -> str:
        """Return an overridden value, raising ``KeyError`` if not set."""
        if key in self._overrides:
            return self._overrides[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: str) -> None:
        """Set an override, dropping any prior ``unset`` flag."""
        self._overrides[key] = value
        self._hidden.discard(key)

    def __delitem__(self, key: str) -> None:
        """Drop an override; raise if the key was never overridden."""
        if key not in self._overrides:
            raise KeyError(key)
        del self._overrides[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate over override keys."""
        return iter(self._overrides)

    def __len__(self) -> int:
        """Return the override count."""
        return len(self._overrides)

    def unset(self, key: str) -> None:
        """Hide `key` from any base mapping during merging or activation."""
        self._hidden.add(key)
        self._overrides.pop(key, None)

    def restore(self, key: str) -> None:
        """Drop any override or hide flag for `key`."""
        self._overrides.pop(key, None)
        self._hidden.discard(key)

    def merged(self, base: Mapping[str, str]) -> dict[str, str]:
        """Compose the overlay onto `base` and return a fresh dict."""
        merged = {k: v for k, v in base.items() if k not in self._hidden}
        merged.update(self._overrides)
        return merged

    @property
    def hidden(self) -> frozenset[str]:
        """Keys hidden from the base mapping."""
        return frozenset(self._hidden)

    @property
    def overrides(self) -> dict[str, str]:
        """A copy of the override map."""
        return dict(self._overrides)

    def __getstate__(self) -> dict[str, Any]:
        """Make the overlay safely picklable across subprocess transfers."""
        return {
            "overrides": dict(self._overrides),
            "hidden": list(self._hidden),
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore overlay state during unpickling."""
        self._overrides = dict(state["overrides"])
        self._hidden = set(state["hidden"])


class Environment:
    """Per-scope filesystem + env-var sandbox handle.

    Implements the ``SyncableResource[EnvironmentSyncState]`` protocol
    structurally; the ABC subclass relationship is established lazily by
    ``rue.resources.builtins`` to break a module-load cycle with
    ``rue.resources``.

    Construction is restricted to ``_build`` because each instance needs to
    know its scope owner; resource factories use that classmethod, tests
    should never call it directly.
    """

    __slots__ = (
        "_baseline",
        "_cwd",
        "_provider_spec",
        "_root",
        "_saved_cwd",
        "_saved_environ",
        "_scope",
        "_subprocess_checkpoint",
        "_vars",
    )

    def __init__(self, *, root: Path, scope: Scope) -> None:
        self._root = root.resolve()
        self._scope = scope
        self._cwd = self._root
        self._vars = EnvironmentVars()
        self._provider_spec: ResourceSpec | None = None
        self._baseline: Checkpoint | None = None
        self._subprocess_checkpoint: Checkpoint | None = None

    @classmethod
    def _build(cls, *, root: Path, scope: Scope) -> Environment:
        """Construct an environment rooted at `root` for resource factories."""
        return cls(root=root, scope=scope)

    @property
    def root(self) -> Path:
        """Sandbox root."""
        return self._root

    @property
    def cwd(self) -> Path:
        """Current default working directory inside the sandbox."""
        return self._cwd

    @property
    def vars(self) -> EnvironmentVars:
        """Environment variable overlay."""
        return self._vars

    @property
    def scope(self) -> Scope:
        """The scope that owns this environment."""
        return self._scope

    @property
    def baseline(self) -> Checkpoint:
        """Checkpoint captured by the most recent `set_baseline` call."""
        if self._baseline is None:
            msg = (
                "Environment baseline is not set. Call "
                "`environment.set_baseline()` before reading "
                "`environment.baseline` or `environment.diff`."
            )
            raise RuntimeError(msg)
        return self._baseline

    @property
    def diff(self) -> Diff:
        """Diff the current filesystem against the explicit baseline."""
        baseline = self.baseline
        return Diff.from_checkpoints(
            baseline, Checkpoint.from_root(self._root)
        )

    def set_baseline(self) -> None:
        """Capture the current filesystem state for future `diff` calls."""
        self._baseline = Checkpoint.from_root(self._root)

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
        target = self.path(p)
        if not target.is_dir():
            msg = f"chdir target is not a directory: {target}"
            raise NotADirectoryError(msg)
        self._cwd = target
        if _ACTIVE_ENVIRONMENT is self:
            os.chdir(target)

    def reset(self) -> None:
        """Empty the sandbox, clear the cwd and explicit baseline."""
        empty_tree(self._root)
        self._cwd = self._root
        self._baseline = None

    async def load(self, source: Source) -> None:
        """Materialize `source` into the sandbox and clear the baseline."""
        storage = EnvironmentStorage()
        await source.materialize(
            cache_root=storage.cache_dir,
            dst=self._root,
        )
        self._baseline = None
        self._cwd = self._root

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

        base = dict(os.environ) if inherit_os else {}
        merged_env = self._vars.merged(base)
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

    def get_sync_state(self) -> EnvironmentSyncState:
        """Return state safe for subprocess transport.

        Direction matters:
          * Parent → worker: ships ``parent_root`` and a baseline manifest
            so the worker can reflink-clone.
          * Worker → parent: ships ``deltas`` computed against the baseline
            captured by ``from_sync_state``.
        """
        baseline_checkpoint = self._subprocess_checkpoint
        manifest_checkpoint = baseline_checkpoint or Checkpoint.from_root(
            self._root
        )
        deltas: tuple[FileDelta, ...] = ()
        if baseline_checkpoint is not None:
            current = Checkpoint.from_root(self._root)
            diff = Diff.from_checkpoints(baseline_checkpoint, current)
            delta_list: list[FileDelta] = []
            for path in diff.added:
                delta_list.append(
                    FileDelta.from_path(self._root, path, FileDeltaKind.ADDED)
                )
            for path in diff.modified:
                delta_list.append(
                    FileDelta.from_path(
                        self._root, path, FileDeltaKind.MODIFIED
                    )
                )
            for path in diff.deleted:
                delta_list.append(
                    FileDelta(path=path, kind=FileDeltaKind.DELETED)
                )
            deltas = tuple(delta_list)
        relative_cwd = PurePosixPath(
            self._cwd.resolve().relative_to(self._root).as_posix() or "."
        )
        return EnvironmentSyncState(
            parent_root=self._root,
            baseline_manifest=tuple(manifest_checkpoint.entries.values()),
            diff_baseline_manifest=(
                tuple(self._baseline.entries.values())
                if self._baseline is not None
                else None
            ),
            overrides=dict(self._vars.overrides),
            hidden=frozenset(self._vars.hidden),
            cwd=relative_cwd,
            scope_value=self._scope.value,
            deltas=deltas,
        )

    def from_sync_state(self, state: EnvironmentSyncState) -> None:
        """Hydrate this worker-side env from a parent-shipped state."""
        if state.parent_root != self._root:
            empty_tree(self._root)
            self._root.rmdir()
            clone_tree(state.parent_root, self._root)
        self._vars = EnvironmentVars()
        for key, value in state.overrides.items():
            self._vars[key] = value
        for key in state.hidden:
            self._vars.unset(key)
        target_cwd = (self._root / Path(state.cwd)).resolve()
        if not target_cwd.is_relative_to(self._root):
            target_cwd = self._root
        self._cwd = target_cwd
        self._subprocess_checkpoint = Checkpoint.from_manifest(
            self._root, state.baseline_manifest
        )
        self._baseline = (
            Checkpoint.from_manifest(self._root, state.diff_baseline_manifest)
            if state.diff_baseline_manifest is not None
            else None
        )

    def merge_sync_states(
        self,
        baseline: EnvironmentSyncState,
        update: EnvironmentSyncState,
    ) -> None:
        """Apply worker-emitted deltas back into the parent root."""
        del baseline
        for delta in update.deltas:
            target = self._root / delta.path
            match delta.kind:
                case FileDeltaKind.DELETED:
                    if target.is_symlink() or target.exists():
                        if target.is_dir() and not target.is_symlink():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                case FileDeltaKind.ADDED | FileDeltaKind.MODIFIED:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_symlink() or target.exists():
                        if target.is_dir() and not target.is_symlink():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    if delta.symlink_target is not None:
                        os.symlink(delta.symlink_target, target)
                        continue
                    payload = delta.content or b""
                    target.write_bytes(payload)
                    os.chmod(target, delta.mode)
        for key, value in update.overrides.items():
            self._vars[key] = value
        for key in update.hidden:
            self._vars.unset(key)
        self._baseline = (
            Checkpoint.from_manifest(self._root, update.diff_baseline_manifest)
            if update.diff_baseline_manifest is not None
            else None
        )

    def __enter__(self) -> Environment:
        """Bind this env to the current process: cwd + os.environ.

        Activation is exclusive across the process: a non-blocking lock
        acquire turns both re-entrant nesting and concurrent activation
        from another thread into an immediate ``RuntimeError`` instead of a
        silent deadlock.
        """
        global _ACTIVE_ENVIRONMENT
        if not _ACTIVATION_LOCK.acquire(blocking=False):
            msg = (
                "Another Environment is already active in this process. "
                "Activation does not nest and is not concurrent-safe; keep "
                "`with environment:` blocks tight around the call that "
                "needs the sandbox."
            )
            raise RuntimeError(msg)
        self._saved_environ = dict(os.environ)
        self._saved_cwd = os.getcwd()
        new_environ = self._vars.merged(self._saved_environ)
        os.environ.clear()
        os.environ.update(new_environ)
        os.chdir(self._cwd)
        _ACTIVE_ENVIRONMENT = self
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Restore the saved cwd and os.environ; release the activation lock."""
        global _ACTIVE_ENVIRONMENT
        try:
            os.chdir(self._saved_cwd)
            os.environ.clear()
            os.environ.update(self._saved_environ)
        finally:
            _ACTIVE_ENVIRONMENT = None
            _ACTIVATION_LOCK.release()


__all__ = [
    "Environment",
    "EnvironmentVars",
]
