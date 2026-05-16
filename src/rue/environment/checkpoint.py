"""Filesystem checkpoints and diffs for Rue environments."""

from __future__ import annotations

import difflib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, cast

import fast_diff_match_patch  # type: ignore[import-not-found]
import jsonpatch  # type: ignore[import-untyped]

import bsdiff4


@dataclass(frozen=True, slots=True)
class UpdatedPath:
    """One changed path in an environment checkpoint."""

    path: PurePosixPath
    deleted: bool
    symlink: bool
    mode: int | None
    bsdiff_patch: bytes | str | None

    @classmethod
    def deleted_path(cls, path: PurePosixPath) -> UpdatedPath:
        """Create an update for a removed path."""
        return cls(
            path=path,
            deleted=True,
            symlink=False,
            mode=None,
            bsdiff_patch=None,
        )

    @classmethod
    def file(
        cls,
        path: PurePosixPath,
        *,
        mode: int | None,
        bsdiff_patch: bytes | None,
    ) -> UpdatedPath:
        """Create an update or reconstructed state for a regular file."""
        return cls(
            path=path,
            deleted=False,
            symlink=False,
            mode=mode,
            bsdiff_patch=bsdiff_patch,
        )

    @classmethod
    def symlink_path(cls, path: PurePosixPath, target: str) -> UpdatedPath:
        """Create an update or reconstructed state for a symlink."""
        return cls(
            path=path,
            deleted=False,
            symlink=True,
            mode=None,
            bsdiff_patch=target,
        )

    @property
    def bytes(self) -> Any:
        """Regular-file bytes or bsdiff payload."""
        return self.bsdiff_patch

    @property
    def target(self) -> Any:
        """Symlink target payload."""
        return self.bsdiff_patch


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Filesystem checkpoint as updates over an optional baseline tree."""

    baseline: Path | None
    updated_paths: tuple[UpdatedPath, ...]

    @classmethod
    def from_root(cls, root: Path, baseline: Path | None = None) -> Checkpoint:
        """Capture changed files and symlinks under `root`.

        `baseline=None` represents an empty baseline. Directories are skipped
        because their presence is implied by files and symlinks.
        """
        root = root.resolve()
        baseline = baseline.resolve() if baseline is not None else None
        baseline_states = _read_states(baseline)
        current_states = _read_states(root)
        updated_paths: list[UpdatedPath] = []

        for path in sorted(baseline_states.keys() | current_states.keys()):
            baseline_state = baseline_states.get(path)
            current_state = current_states.get(path)
            if current_state is None:
                updated_paths.append(UpdatedPath.deleted_path(path))
                continue
            if current_state == baseline_state:
                continue
            if current_state.symlink:
                updated_paths.append(
                    UpdatedPath.symlink_path(
                        path,
                        current_state.target,
                    )
                )
                continue

            baseline_bytes = b""
            if baseline_state is not None and not baseline_state.symlink:
                baseline_bytes = baseline_state.bytes
            current_bytes = current_state.bytes
            updated_paths.append(
                UpdatedPath.file(
                    path=path,
                    mode=current_state.mode,
                    bsdiff_patch=(
                        bsdiff4.diff(baseline_bytes, current_bytes)
                        if baseline_bytes != current_bytes
                        else None
                    ),
                )
            )
        return cls(baseline=baseline, updated_paths=tuple(updated_paths))

    def compare(self, checkpoint: Checkpoint) -> Diff:
        """Return the diff from this checkpoint to `checkpoint`.

        `self` is the earlier/reference checkpoint. `checkpoint` is the later
        checkpoint being compared against it.
        """
        baseline_states = self._final_states()
        current_states = checkpoint._final_states()
        added = tuple(
            sorted(current_states.keys() - baseline_states.keys())
        )
        deleted = tuple(
            sorted(baseline_states.keys() - current_states.keys())
        )
        modified = tuple(
            sorted(
                path
                for path in baseline_states.keys() & current_states.keys()
                if baseline_states[path] != current_states[path]
            )
        )
        return Diff(
            added=added,
            modified=modified,
            deleted=deleted,
            before_files={
                path: _state_payload(baseline_states[path])
                for path in (*modified, *deleted)
            },
            after_files={
                path: _state_payload(current_states[path])
                for path in (*modified, *added)
            },
        )

    def _final_states(self) -> dict[PurePosixPath, UpdatedPath]:
        states = _read_states(self.baseline)
        for updated_path in self.updated_paths:
            if updated_path.deleted:
                states.pop(updated_path.path, None)
                continue
            if updated_path.symlink:
                states[updated_path.path] = UpdatedPath.symlink_path(
                    updated_path.path,
                    updated_path.target,
                )
                continue

            baseline_state = states.get(updated_path.path)
            baseline_bytes = b""
            if baseline_state is not None and not baseline_state.symlink:
                baseline_bytes = baseline_state.bytes
            if updated_path.bsdiff_patch is None:
                payload = baseline_bytes
            else:
                payload = bsdiff4.patch(baseline_bytes, updated_path.bytes)
            states[updated_path.path] = UpdatedPath.file(
                path=updated_path.path,
                mode=updated_path.mode,
                bsdiff_patch=payload,
            )
        return states


def _read_states(root: Path | None) -> dict[PurePosixPath, UpdatedPath]:
    states: dict[PurePosixPath, UpdatedPath] = {}
    if root is None:
        return states

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in [*dirnames, *filenames]:
            absolute = Path(dirpath, name)
            stat_result = os.lstat(absolute)
            mode = stat_result.st_mode
            if stat.S_ISDIR(mode):
                continue
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            if stat.S_ISLNK(mode):
                states[relative] = UpdatedPath.symlink_path(
                    relative,
                    os.readlink(absolute),
                )
                continue
            if stat.S_ISREG(mode):
                states[relative] = UpdatedPath.file(
                    path=relative,
                    mode=stat.S_IMODE(mode),
                    bsdiff_patch=absolute.read_bytes(),
                )
    return states

def _state_payload(state: UpdatedPath) -> bytes:
    """Return file bytes or the UTF-8-encoded symlink target."""
    if state.symlink:
        return cast(str, state.target).encode()
    return cast(bytes, state.bytes)


@dataclass(frozen=True, slots=True)
class FileDiff:
    """Per-file diff rendered as unified text, word DMP, or JSON Patch."""

    path: PurePosixPath
    before: bytes
    after: bytes

    @property
    def unified(self) -> str:
        """Return ``difflib.unified_diff`` output as a single string."""
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
        """Return word-level diff as raw DMP ``(op, text)`` tuples."""
        before_chars, after_chars, vocab = _tokens_to_chars(
            self.before.decode(),
            self.after.decode(),
        )
        raw = fast_diff_match_patch.diff(
            before_chars,
            after_chars,
            counts_only=False,
            cleanup="Semantic",
        )
        return tuple(
            (op, "".join(vocab[ord(c)] for c in chars)) for op, chars in raw
        )

    @property
    def json(self) -> list[dict[str, Any]]:
        """Return an RFC 6902 JSON Patch between ``before`` and ``after``."""
        before = json.loads(self.before) if self.before else None
        after = json.loads(self.after) if self.after else None
        return list(jsonpatch.make_patch(before, after))


def _tokens_to_chars(
    text_a: str, text_b: str
) -> tuple[str, str, list[str]]:
    """Rebase whitespace/word tokens to single Unicode codepoints for DMP."""
    vocab: list[str] = []
    index: dict[str, int] = {}

    def rebase(text: str) -> str:
        chars: list[str] = []
        for token in re.findall(r"\s+|\S+", text):
            i = index.get(token)
            if i is None:
                i = len(vocab)
                index[token] = i
                vocab.append(token)
            chars.append(chr(i))
        return "".join(chars)

    return rebase(text_a), rebase(text_b), vocab


@dataclass(frozen=True, slots=True)
class Diff:
    """Diff between two checkpoints."""

    added: tuple[PurePosixPath, ...] = ()
    modified: tuple[PurePosixPath, ...] = ()
    deleted: tuple[PurePosixPath, ...] = ()
    before_files: Mapping[PurePosixPath, bytes] = field(default_factory=dict)
    after_files: Mapping[PurePosixPath, bytes] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """True when there are no changes."""
        return not (self.added or self.modified or self.deleted)

    def diff(self, path: str | PurePosixPath) -> FileDiff:
        """Return a per-file diff view for a changed path."""
        key = PurePosixPath(path)
        if key not in self.before_files and key not in self.after_files:
            raise KeyError(key)
        return FileDiff(
            path=key,
            before=self.before_files.get(key, b""),
            after=self.after_files.get(key, b""),
        )

    def content(self, path: str | PurePosixPath) -> bytes:
        """Return surviving bytes: after-state, or before-state for deleted."""
        key = PurePosixPath(path)
        if key in self.after_files:
            return self.after_files[key]
        return self.before_files[key]


__all__ = [
    "Checkpoint",
    "Diff",
    "FileDiff",
    "UpdatedPath",
]
