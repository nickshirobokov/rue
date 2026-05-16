"""Filesystem checkpoints and diffs for Rue environments."""

from __future__ import annotations

import difflib
import json
import os
import re
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import jsonpatch  # type: ignore[import-untyped]

import bsdiff4


# --- Storage variants (deltas relative to a baseline) ----------------------


@dataclass(frozen=True, slots=True)
class FileDelta:
    """File mode and/or byte change relative to the baseline tree."""

    path: PurePosixPath
    mode: int
    patch: bytes | None  # None when only the mode changed


@dataclass(frozen=True, slots=True)
class SymlinkDelta:
    """Final target of a created or retargeted symlink."""

    path: PurePosixPath
    target: str


@dataclass(frozen=True, slots=True)
class Deletion:
    """Marker for a path that existed in the baseline and no longer does."""

    path: PurePosixPath


PathDelta = FileDelta | SymlinkDelta | Deletion


# --- Reconstructed view variants -------------------------------------------


@dataclass(frozen=True, slots=True)
class FileState:
    """Fully-materialized regular file."""

    path: PurePosixPath
    mode: int
    content: bytes


@dataclass(frozen=True, slots=True)
class SymlinkState:
    """Fully-materialized symlink."""

    path: PurePosixPath
    target: str

    @property
    def content(self) -> bytes:
        """UTF-8-encoded target; mirrors ``FileState.content`` for unions."""
        return self.target.encode()


PathState = FileState | SymlinkState


# --- User-facing exception -------------------------------------------------


class PathNotInDiff(KeyError):  # noqa: N818 — user-facing name, no Error suffix
    """Raised when a path is not part of a ``Diff``."""


# --- Filesystem walk -------------------------------------------------------


def _read_states(
    root: Path | None,
    *,
    reuse: Mapping[PurePosixPath, PathState] | None = None,
    reuse_fingerprints: Mapping[PurePosixPath, tuple[int, int]] | None = None,
) -> tuple[
    dict[PurePosixPath, PathState],
    dict[PurePosixPath, tuple[int, int]],
]:
    """Walk ``root`` and return reconstructed states plus file fingerprints.

    A regular file whose live ``(size, mtime_ns)`` matches an entry in
    ``reuse_fingerprints`` and whose ``reuse`` entry is a ``FileState`` of the
    same mode reuses that entry's content instead of re-reading the bytes.
    """
    reuse = reuse or {}
    reuse_fingerprints = reuse_fingerprints or {}
    states: dict[PurePosixPath, PathState] = {}
    fingerprints: dict[PurePosixPath, tuple[int, int]] = {}
    if root is None:
        return states, fingerprints

    def walk(
        current: Path,
    ) -> Iterator[tuple[PurePosixPath, str, os.stat_result]]:
        with os.scandir(current) as entries:
            for entry in entries:
                st = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    yield from walk(Path(entry.path))
                    continue
                relative = PurePosixPath(
                    Path(entry.path).relative_to(root).as_posix()
                )
                yield relative, entry.path, st

    for relative, entry_path, st in walk(root):
        mode = st.st_mode
        if stat.S_ISLNK(mode):
            states[relative] = SymlinkState(
                path=relative, target=os.readlink(entry_path)
            )
            continue
        if not stat.S_ISREG(mode):
            continue
        file_mode = stat.S_IMODE(mode)
        fingerprint = (st.st_size, st.st_mtime_ns)
        fingerprints[relative] = fingerprint
        reused = reuse.get(relative)
        if (
            isinstance(reused, FileState)
            and reused.mode == file_mode
            and reuse_fingerprints.get(relative) == fingerprint
        ):
            states[relative] = reused
            continue
        states[relative] = FileState(
            path=relative,
            mode=file_mode,
            content=Path(entry_path).read_bytes(),
        )
    return states, fingerprints


# --- Checkpoint ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Filesystem checkpoint stored as deltas over an optional baseline tree."""

    baseline: Path | None
    updated_paths: tuple[PathDelta, ...]
    _states_cache: Mapping[PurePosixPath, PathState] | None = field(
        default=None, compare=False, repr=False
    )

    @classmethod
    def from_root(
        cls, root: Path, baseline: Path | None = None
    ) -> Checkpoint:
        """Capture changed files and symlinks under ``root``.

        ``baseline=None`` represents an empty baseline. When a baseline is
        supplied, files whose live ``(size, mtime_ns)`` matches the baseline's
        recorded fingerprint reuse the baseline content without a re-read.
        """
        root = root.resolve()
        baseline = baseline.resolve() if baseline is not None else None
        baseline_states, baseline_fingerprints = _read_states(baseline)
        current_states, _ = _read_states(
            root,
            reuse=baseline_states,
            reuse_fingerprints=baseline_fingerprints,
        )

        deltas: list[PathDelta] = []
        for path in sorted(baseline_states.keys() | current_states.keys()):
            baseline_state = baseline_states.get(path)
            current_state = current_states.get(path)
            if current_state is None:
                deltas.append(Deletion(path=path))
                continue
            if current_state == baseline_state:
                continue
            if isinstance(current_state, SymlinkState):
                deltas.append(
                    SymlinkDelta(path=path, target=current_state.target)
                )
                continue
            baseline_bytes = (
                baseline_state.content
                if isinstance(baseline_state, FileState)
                else b""
            )
            patch: bytes | None = (
                None
                if baseline_bytes == current_state.content
                else bsdiff4.diff(baseline_bytes, current_state.content)
            )
            deltas.append(
                FileDelta(path=path, mode=current_state.mode, patch=patch)
            )

        return cls(baseline=baseline, updated_paths=tuple(deltas))

    def compare(self, checkpoint: Checkpoint) -> Diff:
        """Return the diff from ``self`` to ``checkpoint``.

        ``self`` is the earlier/reference checkpoint. ``checkpoint`` is the
        later one being compared against it.
        """
        before = self.final_states
        after = checkpoint.final_states
        return Diff(
            added=tuple(sorted(after.keys() - before.keys())),
            modified=tuple(
                sorted(
                    p
                    for p in before.keys() & after.keys()
                    if before[p] != after[p]
                )
            ),
            deleted=tuple(sorted(before.keys() - after.keys())),
            _before=self,
            _after=checkpoint,
        )

    @property
    def final_states(self) -> Mapping[PurePosixPath, PathState]:
        """Fully-reconstructed final state, memoized per instance."""
        cached = self._states_cache
        if cached is not None:
            return cached
        states, _ = _read_states(self.baseline)
        for delta in self.updated_paths:
            if isinstance(delta, Deletion):
                states.pop(delta.path, None)
                continue
            if isinstance(delta, SymlinkDelta):
                states[delta.path] = SymlinkState(
                    path=delta.path, target=delta.target
                )
                continue
            baseline_bytes = b""
            existing = states.get(delta.path)
            if isinstance(existing, FileState):
                baseline_bytes = existing.content
            content = (
                baseline_bytes
                if delta.patch is None
                else bsdiff4.patch(baseline_bytes, delta.patch)
            )
            states[delta.path] = FileState(
                path=delta.path, mode=delta.mode, content=content
            )
        result = MappingProxyType(states)
        object.__setattr__(self, "_states_cache", result)
        return result


# --- FileDiff (per-file diff views) ----------------------------------------


@dataclass(frozen=True, slots=True)
class FileDiff:
    """Per-file diff rendered as unified text, word DMP, or JSON Patch."""

    path: PurePosixPath
    before: bytes
    after: bytes

    @property
    def unified(self) -> str:
        """``difflib.unified_diff`` output as a single string."""
        label = str(self.path)
        return "".join(
            difflib.unified_diff(
                self.before.decode().splitlines(keepends=True),
                self.after.decode().splitlines(keepends=True),
                fromfile=label,
                tofile=label,
            )
        )

    @property
    def words(self) -> tuple[tuple[str, str], ...]:
        """Word-level diff as ``(op, text)`` tuples; op in ``{=, -, +}``."""
        before_tokens = re.findall(r"\s+|\S+", self.before.decode())
        after_tokens = re.findall(r"\s+|\S+", self.after.decode())
        out: list[tuple[str, str]] = []
        matcher = difflib.SequenceMatcher(
            a=before_tokens, b=after_tokens, autojunk=False
        )
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                out.append(("=", "".join(before_tokens[i1:i2])))
            elif op == "delete":
                out.append(("-", "".join(before_tokens[i1:i2])))
            elif op == "insert":
                out.append(("+", "".join(after_tokens[j1:j2])))
            else:  # replace
                out.append(("-", "".join(before_tokens[i1:i2])))
                out.append(("+", "".join(after_tokens[j1:j2])))
        return tuple(out)

    @property
    def json(self) -> list[dict[str, Any]]:
        """RFC 6902 JSON Patch between ``before`` and ``after``."""
        before = json.loads(self.before) if self.before else None
        after = json.loads(self.after) if self.after else None
        return list(jsonpatch.make_patch(before, after))


# --- Diff ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Diff:
    """Diff between two checkpoints. File content is reconstructed lazily."""

    added: tuple[PurePosixPath, ...] = ()
    modified: tuple[PurePosixPath, ...] = ()
    deleted: tuple[PurePosixPath, ...] = ()
    _before: Checkpoint | None = field(
        default=None, compare=False, repr=False
    )
    _after: Checkpoint | None = field(
        default=None, compare=False, repr=False
    )

    @property
    def empty(self) -> bool:
        """True when there are no changes."""
        return not (self.added or self.modified or self.deleted)

    def __bool__(self) -> bool:
        """True when there is at least one change."""
        return not self.empty

    def __len__(self) -> int:
        """Total number of changed paths."""
        return len(self.added) + len(self.modified) + len(self.deleted)

    def __iter__(self) -> Iterator[PurePosixPath]:
        """Yield every changed path in sorted order."""
        yield from sorted({*self.added, *self.modified, *self.deleted})

    def __contains__(self, path: object) -> bool:
        """Whether ``path`` is among the changed paths."""
        try:
            key = PurePosixPath(path)  # type: ignore[arg-type]
        except TypeError:
            return False
        return (
            key in self.added
            or key in self.modified
            or key in self.deleted
        )

    def diff(self, path: str | PurePosixPath) -> FileDiff:
        """Return a per-file diff view for a changed path."""
        key = PurePosixPath(path)
        if key not in self:
            raise PathNotInDiff(
                f"{key} not in this diff "
                f"(changed: {[str(p) for p in self]})"
            )
        before_state = (
            self._before.final_states.get(key)
            if self._before is not None
            else None
        )
        after_state = (
            self._after.final_states.get(key)
            if self._after is not None
            else None
        )
        return FileDiff(
            path=key,
            before=before_state.content if before_state else b"",
            after=after_state.content if after_state else b"",
        )


__all__ = [
    "Checkpoint",
    "Deletion",
    "Diff",
    "FileDelta",
    "FileDiff",
    "FileState",
    "PathDelta",
    "PathNotInDiff",
    "PathState",
    "SymlinkDelta",
    "SymlinkState",
]
