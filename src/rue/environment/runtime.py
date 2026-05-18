"""Environment handle, env-var overlay, and context-routed activation."""

from __future__ import annotations

import asyncio
import errno
import subprocess
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from rue.context.scopes import Scope
from rue.environment.checkpoint import Checkpoint, Diff
from rue.environment.dispatch.current import (
    activate,
    deactivate,
)
from rue.environment.dispatch.environ import real_environ
from rue.environment.sources import Source
from rue.environment.storage import (
    EnvironmentStorage,
    clone_tree,
    empty_tree,
)
from rue.environment.sync import EnvironmentSyncState


class EnvironmentVars(MutableMapping[str, str]):
    """Override layer over `os.environ` for an `Environment`.

    Stores user-supplied overrides and a set of "hidden" keys to mask.
    `view(base)` returns a live `MutableMapping` composed onto an arbitrary
    base mapping, used by the dispatcher routers and `Environment.exec`.
    """

    __slots__ = ("_hidden", "_overrides")

    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}
        self._hidden: set[str] = set()

    def __getitem__(self, key: str) -> str:
        """Return an overridden value, raising ``KeyError`` if not set."""
        self._check_key(key)
        if key in self._overrides:
            return self._overrides[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: str) -> None:
        """Set an override, dropping any prior ``unset`` flag."""
        self._check_key(key)
        self._check_value(value)
        self._overrides[key] = value
        self._hidden.discard(key)

    def __delitem__(self, key: str) -> None:
        """Drop an override; raise if the key was never overridden."""
        self._check_key(key)
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
        self._check_key(key)
        self._hidden.add(key)
        self._overrides.pop(key, None)

    def restore(self, key: str) -> None:
        """Drop any override or hide flag for `key`."""
        self._check_key(key)
        self._overrides.pop(key, None)
        self._hidden.discard(key)

    def view(self, base: Mapping[str, str]) -> MergedView:
        """Return a live `MutableMapping` of this overlay composed on `base`."""
        return MergedView(self, base)

    @staticmethod
    def _check_key(key: str) -> None:
        if not isinstance(key, str):
            raise TypeError(f"str expected, not {type(key).__name__}")
        if key == "":
            raise OSError(errno.EINVAL, "Invalid argument")
        if "=" in key:
            raise ValueError("illegal environment variable name")
        if "\x00" in key:
            raise ValueError("embedded null byte")

    @staticmethod
    def _check_value(value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"str expected, not {type(value).__name__}")
        if "\x00" in value:
            raise ValueError("embedded null byte")

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
        self._overrides = {}
        self._hidden = set()
        for key, value in state["overrides"].items():
            self[key] = value
        for key in state["hidden"]:
            self.unset(key)


class MergedView(MutableMapping[str, str]):
    """Live `EnvironmentVars` overlay composed onto a base mapping.

    Reads consult the overlay first (returning an override or raising for
    a hidden key) and fall through to the base. Writes set on the
    overlay; deletes hide the key from any base value as well.
    """

    __slots__ = ("_base", "_overlay")

    def __init__(
        self, overlay: EnvironmentVars, base: Mapping[str, str]
    ) -> None:
        self._overlay = overlay
        self._base = base

    def __getitem__(self, key: str) -> str:
        EnvironmentVars._check_key(key)
        if key in self._overlay._hidden:
            raise KeyError(key)
        if key in self._overlay._overrides:
            return self._overlay._overrides[key]
        return self._base[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._overlay[key] = value

    def __delitem__(self, key: str) -> None:
        EnvironmentVars._check_key(key)
        if key in self._overlay._hidden:
            raise KeyError(key)
        if key not in self._overlay._overrides and key not in self._base:
            raise KeyError(key)
        self._overlay.unset(key)

    def __iter__(self) -> Iterator[str]:
        for key in self._base:
            if key in self._overlay._hidden or key in self._overlay._overrides:
                continue
            yield key
        yield from self._overlay._overrides

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self._overlay._hidden:
            return False
        if key in self._overlay._overrides:
            return True
        return key in self._base


class Environment:
    """Per-scope filesystem + env-var sandbox handle.

    Implements the ``SyncableResource[EnvironmentSyncState]`` protocol
    structurally; the ABC subclass relationship is established lazily by
    ``rue.resources.builtins`` to break a module-load cycle with
    ``rue.resources``.

    Each instance knows the scope owner for its filesystem root.
    """

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
        self._vars = EnvironmentVars()

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

    def get_checkpoint(self) -> Checkpoint:
        """Return a filesystem checkpoint without mutating environment state."""
        return Checkpoint.from_root(self._root, self._cache_path)

    def get_diff(self, baseline: Checkpoint | None = None) -> Diff:
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

    def reset(self) -> None:
        """Restore the sandbox from its cached baseline and reset the cwd."""
        empty_tree(self._root)
        if self._cache_path is not None:
            for child in self._cache_path.iterdir():
                clone_tree(child, self._root / child.name)
        self._cwd = self._root

    async def load(self, source: Source) -> None:
        """Materialize `source` into the sandbox and reset the cwd."""
        storage = EnvironmentStorage()
        self._cache_path = await source.materialize(
            cache_root=storage.cache_dir,
            dst=self._root,
        )
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

        base = dict(real_environ()) if inherit_os else {}
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
        self._vars = EnvironmentVars()
        for key, value in state.overrides.items():
            self._vars[key] = value
        for key in state.hidden:
            self._vars.unset(key)
        target_cwd = (self._root / Path(state.cwd)).resolve()
        if not target_cwd.is_relative_to(self._root):
            target_cwd = self._root
        self._cwd = target_cwd

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
        self._cwd = target_cwd
        self._vars = EnvironmentVars()
        for key, value in update.overrides.items():
            self._vars[key] = value
        for key in update.hidden:
            self._vars.unset(key)

    def __enter__(self) -> Environment:
        """Bind this env as the active routing target for the current context.

        Activation is context-local: nested and concurrent ``with`` blocks
        each push an entry onto a per-context stack. The chokepoint
        dispatchers (``os.environ``, ``os.getcwd``, ``open``, ...) read
        from this binding to route per-test instead of mutating shared
        process state.
        """
        activate(self)
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Pop this env from the per-context activation stack."""
        deactivate(self)


__all__ = [
    "Environment",
    "EnvironmentVars",
]
