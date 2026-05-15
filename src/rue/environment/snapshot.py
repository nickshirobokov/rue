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

    @classmethod
    def from_root(cls, root: Path) -> Snapshot:
        """Walk `root` and snapshot every file and symlink under it.

        Directories are skipped because their existence is implied by entries
        inside them. Symlinks are recorded but never followed.
        """
        root = root.resolve()
        entries: dict[PurePosixPath, FileEntry] = {}
        if not root.exists():
            return cls(root=root, entries=entries)

        for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                absolute = Path(dirpath, name)
                try:
                    stat_result = os.lstat(absolute)
                except FileNotFoundError:
                    continue
                mode = stat_result.st_mode
                relative = PurePosixPath(
                    absolute.relative_to(root).as_posix()
                )
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
        return cls(root=root, entries=entries)


def hash_file(path: Path) -> str:
    """Return a BLAKE2b digest of `path`'s byte contents."""
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Diff:
    """Diff between two snapshots."""

    added: tuple[PurePosixPath, ...] = ()
    modified: tuple[PurePosixPath, ...] = ()
    deleted: tuple[PurePosixPath, ...] = ()

    @classmethod
    def from_snapshots(
        cls,
        base: Snapshot,
        modified: Snapshot,
    ) -> Diff:
        """Compare `base` to `modified` snapshot manifests.

        A path is considered modified when size, mode, symlink target, or
        `(size, mtime_ns)` differ. When metadata is identical content is
        assumed identical; when only mtime differs we hash both files to break
        the tie. Hash comparisons run inside `base.root` and `modified.root`.
        """
        added_paths: list[PurePosixPath] = []
        modified_paths: list[PurePosixPath] = []
        deleted_paths: list[PurePosixPath] = []

        for path, current_entry in modified.entries.items():
            baseline_entry = base.entries.get(path)
            if baseline_entry is None:
                added_paths.append(path)
                continue
            if baseline_entry.symlink_target != current_entry.symlink_target:
                modified_paths.append(path)
                continue
            if baseline_entry.is_symlink:
                continue
            if (
                baseline_entry.mode != current_entry.mode
                or baseline_entry.size != current_entry.size
            ):
                modified_paths.append(path)
                continue
            if baseline_entry.mtime_ns == current_entry.mtime_ns:
                continue
            baseline_hash = baseline_entry.content_hash or hash_file(
                base.root / baseline_entry.path
            )
            current_hash = current_entry.content_hash or hash_file(
                modified.root / current_entry.path
            )
            if baseline_hash != current_hash:
                modified_paths.append(path)

        for path in base.entries:
            if path not in modified.entries:
                deleted_paths.append(path)

        added_paths.sort()
        modified_paths.sort()
        deleted_paths.sort()
        return cls(
            added=tuple(added_paths),
            modified=tuple(modified_paths),
            deleted=tuple(deleted_paths),
        )

    @property
    def empty(self) -> bool:
        """True when there are no changes."""
        return not (self.added or self.modified or self.deleted)


__all__ = [
    "Diff",
    "FileEntry",
    "Snapshot",
    "hash_file",
]
