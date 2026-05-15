"""Filesystem snapshots and diffs for Rue environments."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


_HASH_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One entry in an environment snapshot manifest.

    Symlinks carry their target in `symlink_target` and have an empty
    `content_hash`. Directories are not recorded as their own entries; their
    presence is implied by their children.
    """

    path: PurePosixPath
    size: int
    mtime_ns: int
    mode: int
    symlink_target: str | None = None
    content_hash: str | None = None

    @property
    def is_symlink(self) -> bool:
        """True if this entry represents a symbolic link."""
        return self.symlink_target is not None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Filesystem snapshot rooted at a single directory.

    Entries are keyed by path so equality checks across two snapshots only
    need a dict lookup. The root path is informational and not part of any
    diff.
    """

    root: Path
    entries: dict[PurePosixPath, FileEntry] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Diff:
    """Diff between two snapshots."""

    added: tuple[PurePosixPath, ...] = ()
    modified: tuple[PurePosixPath, ...] = ()
    deleted: tuple[PurePosixPath, ...] = ()

    @property
    def empty(self) -> bool:
        """True when there are no changes."""
        return not (self.added or self.modified or self.deleted)


def scan_snapshot(root: Path) -> Snapshot:
    """Walk `root` and produce a snapshot of every file and symlink under it.

    Directories are skipped because their existence is implied by entries
    inside them. Symlinks are recorded but never followed.
    """
    root = root.resolve()
    entries: dict[PurePosixPath, FileEntry] = {}
    if not root.exists():
        return Snapshot(root=root, entries=entries)

    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            absolute = Path(dirpath, name)
            try:
                stat_result = os.lstat(absolute)
            except FileNotFoundError:
                continue
            mode = stat_result.st_mode
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            symlink_target: str | None = None
            if stat.S_ISLNK(mode):
                try:
                    symlink_target = os.readlink(absolute)
                except OSError:
                    symlink_target = ""
            entries[relative] = FileEntry(
                path=relative,
                size=stat_result.st_size,
                mtime_ns=stat_result.st_mtime_ns,
                mode=stat.S_IMODE(mode),
                symlink_target=symlink_target,
            )
    return Snapshot(root=root, entries=entries)


def hash_file(path: Path) -> str:
    """Return a BLAKE2b digest of `path`'s byte contents."""
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def diff_snapshots(baseline: Snapshot, current: Snapshot) -> Diff:
    """Compute added/modified/deleted paths between two snapshots.

    A path is considered modified when size, mode, symlink target, or
    `(size, mtime_ns)` differ. When metadata is identical content is assumed
    identical; when only mtime differs we hash both files to break the tie.
    Hash comparisons run inside `current.root` and `baseline.root`.
    """
    added: list[PurePosixPath] = []
    modified: list[PurePosixPath] = []
    deleted: list[PurePosixPath] = []

    for path, current_entry in current.entries.items():
        baseline_entry = baseline.entries.get(path)
        if baseline_entry is None:
            added.append(path)
            continue
        if _entries_differ(
            baseline=baseline_entry,
            current=current_entry,
            baseline_root=baseline.root,
            current_root=current.root,
        ):
            modified.append(path)

    for path in baseline.entries:
        if path not in current.entries:
            deleted.append(path)

    added.sort()
    modified.sort()
    deleted.sort()
    return Diff(
        added=tuple(added),
        modified=tuple(modified),
        deleted=tuple(deleted),
    )


def _entries_differ(
    *,
    baseline: FileEntry,
    current: FileEntry,
    baseline_root: Path,
    current_root: Path,
) -> bool:
    if baseline.symlink_target != current.symlink_target:
        return True
    if baseline.is_symlink:
        return False
    if baseline.mode != current.mode:
        return True
    if baseline.size != current.size:
        return True
    if baseline.mtime_ns == current.mtime_ns:
        return False
    baseline_hash = baseline.content_hash or hash_file(
        baseline_root / baseline.path
    )
    current_hash = current.content_hash or hash_file(
        current_root / current.path
    )
    return baseline_hash != current_hash


__all__ = [
    "Diff",
    "FileEntry",
    "Snapshot",
    "diff_snapshots",
    "hash_file",
    "scan_snapshot",
]
