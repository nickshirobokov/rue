"""Filesystem checkpoints and diffs for Rue environments."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath


_HASH_CHUNK_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One entry in an environment checkpoint manifest.

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
class Checkpoint:
    """Filesystem checkpoint rooted at a single directory.

    Entries are keyed by path so equality checks across two checkpoints only
    need a dict lookup. The root path is informational and not part of any
    diff.
    """

    root: Path
    entries: dict[PurePosixPath, FileEntry] = field(default_factory=dict)

    @classmethod
    def from_root(cls, root: Path) -> Checkpoint:
        """Walk `root` and checkpoint every file and symlink under it.

        Directories are skipped because their existence is implied by entries
        inside them. Symlinks are recorded but never followed. Regular files
        store their content hash at capture time, so the checkpoint is a value
        snapshot even when the underlying root is mutated later.
        """
        root = root.resolve()
        entries: dict[PurePosixPath, FileEntry] = {}
        if not root.exists():
            return cls(root=root, entries=entries)

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for name in [*dirnames, *filenames]:
                absolute = Path(dirpath, name)
                try:
                    stat_result = os.lstat(absolute)
                except FileNotFoundError:
                    continue
                mode = stat_result.st_mode
                if stat.S_ISDIR(mode):
                    continue
                relative = PurePosixPath(absolute.relative_to(root).as_posix())
                symlink_target: str | None = None
                content_hash: str | None = None
                if stat.S_ISLNK(mode):
                    try:
                        symlink_target = os.readlink(absolute)
                    except OSError:
                        symlink_target = ""
                elif stat.S_ISREG(mode):
                    try:
                        content_hash = hash_file(absolute)
                    except FileNotFoundError:
                        continue
                entries[relative] = FileEntry(
                    path=relative,
                    size=stat_result.st_size,
                    mtime_ns=stat_result.st_mtime_ns,
                    mode=stat.S_IMODE(mode),
                    symlink_target=symlink_target,
                    content_hash=content_hash,
                )
        return cls(root=root, entries=entries)

    @classmethod
    def from_manifest(
        cls,
        root: Path,
        manifest: tuple[FileEntry, ...],
    ) -> Checkpoint:
        """Build a checkpoint keyed by path from a manifest tuple."""
        return cls(
            root=root,
            entries={entry.path: entry for entry in manifest},
        )

    def compare(self, checkpoint: Checkpoint) -> Diff:
        """Return the diff from this checkpoint to `checkpoint`.

        `self` is the earlier/reference checkpoint. `checkpoint` is the later
        checkpoint being compared against it.
        """
        added_paths: list[PurePosixPath] = []
        modified_paths: list[PurePosixPath] = []
        deleted_paths: list[PurePosixPath] = []

        for path, current_entry in checkpoint.entries.items():
            baseline_entry = self.entries.get(path)
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
            if baseline_entry.content_hash != current_entry.content_hash:
                modified_paths.append(path)
                continue
            if (
                baseline_entry.content_hash is None
                and current_entry.content_hash is None
                and baseline_entry.mtime_ns != current_entry.mtime_ns
            ):
                modified_paths.append(path)

        for path in self.entries:
            if path not in checkpoint.entries:
                deleted_paths.append(path)

        added_paths.sort()
        modified_paths.sort()
        deleted_paths.sort()
        return Diff(
            added=tuple(added_paths),
            modified=tuple(modified_paths),
            deleted=tuple(deleted_paths),
        )


def hash_file(path: Path) -> str:
    """Return a BLAKE2b digest of `path`'s byte contents."""
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Diff:
    """Diff between two checkpoints."""

    added: tuple[PurePosixPath, ...] = ()
    modified: tuple[PurePosixPath, ...] = ()
    deleted: tuple[PurePosixPath, ...] = ()

    @property
    def empty(self) -> bool:
        """True when there are no changes."""
        return not (self.added or self.modified or self.deleted)


__all__ = [
    "Checkpoint",
    "Diff",
    "FileEntry",
    "hash_file",
]
