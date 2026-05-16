"""Environment source kinds and cached materialization."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from rue.environment.storage import clone_tree, empty_tree


class EnvSource(ABC):
    """Abstract base for environment sources.

    Subclasses declare how to fingerprint themselves and how to populate a
    cache directory. The shared orchestration — lock acquisition, cache
    deduplication, and install-into-destination — lives here so each
    concrete type only owns what varies.
    """

    @abstractmethod
    def fingerprint(self) -> str:
        """Return a stable, content-addressed key used to name the cache dir.

        Two sources that should share a cache entry MUST return the same
        fingerprint. Sources whose content could differ MUST return distinct
        fingerprints.
        """

    @abstractmethod
    def _populate_cache(self, cache_dir: Path) -> None:
        """Materialize this source's content into an empty `cache_dir`.

        Called exactly once per unique fingerprint, under an exclusive
        ``fcntl.flock``. ``cache_dir`` does not exist yet when this is
        called; implementations are responsible for creating it.
        """

    async def materialize(self, *, cache_root: Path, dst: Path) -> Path:
        """Materialize this source into `dst` via a content-addressed cache.

        The cache entry for this source is created on first call and reused
        on subsequent ones. Concurrent calls for the same fingerprint are
        deduplicated via an exclusive ``fcntl.flock`` acquired inside a
        thread-pool worker so other coroutines stay responsive.
        """
        fingerprint = await asyncio.to_thread(self.fingerprint)
        cache_dir = cache_root / fingerprint
        cache_root.mkdir(parents=True, exist_ok=True)
        lock_path = cache_root / f"{fingerprint}.lock"
        await asyncio.to_thread(
            self._ensure_cache_populated,
            cache_dir=cache_dir,
            lock_path=lock_path,
        )
        await asyncio.to_thread(
            _install_into_dst,
            cache_dir=cache_dir,
            dst=dst,
        )
        return cache_dir

    def _ensure_cache_populated(
        self,
        *,
        cache_dir: Path,
        lock_path: Path,
    ) -> None:
        """Acquire the per-fingerprint lock and call `_populate_cache` once."""
        handle = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            if cache_dir.exists() and any(cache_dir.iterdir()):
                return
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            self._populate_cache(cache_dir)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
            os.close(handle)


@dataclass(frozen=True, slots=True)
class EmptySource(EnvSource):
    """Source that materializes as an empty directory."""

    def fingerprint(self) -> str:
        """Return a constant fingerprint for the empty source."""
        return hashlib.blake2b(b"empty:", digest_size=16).hexdigest()

    def _populate_cache(self, cache_dir: Path) -> None:
        """Create an empty cache directory."""
        cache_dir.mkdir(parents=True)


@dataclass(frozen=True, slots=True)
class DirSource(EnvSource):
    """Source that clones a host directory into the environment."""

    path: Path

    def fingerprint(self) -> str:
        """Return a fingerprint derived from realpath and file mtimes."""
        digest = hashlib.blake2b(digest_size=16)
        digest.update(b"dir:")
        digest.update(str(self.path.resolve()).encode("utf-8"))
        digest.update(b":")
        digest.update(self._dir_signature().encode("utf-8"))
        return digest.hexdigest()

    def _populate_cache(self, cache_dir: Path) -> None:
        """Reflink-clone the source directory into the cache."""
        clone_tree(self.path.resolve(), cache_dir)

    def _dir_signature(self) -> str:
        """Return a coarse mtime+size digest so edits invalidate the cache."""
        parts: list[str] = []
        real = self.path.resolve()
        if not real.exists():
            return "missing"
        for dirpath, dirnames, filenames in os.walk(real, followlinks=False):
            dirnames.sort()
            for name in sorted(filenames):
                absolute = Path(dirpath, name)
                try:
                    stat_result = os.lstat(absolute)
                except FileNotFoundError:
                    continue
                relative = absolute.relative_to(real).as_posix()
                parts.append(
                    f"{relative}:{stat_result.st_size}:{stat_result.st_mtime_ns}"
                )
        return hashlib.blake2b(
            "\n".join(parts).encode("utf-8"), digest_size=16
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class GitSource(EnvSource):
    """Source that materializes from a remote git ref."""

    url: str
    ref: str
    subpath: Path | None = None

    def fingerprint(self) -> str:
        """Return a fingerprint derived from url, ref, and optional subpath."""
        digest = hashlib.blake2b(digest_size=16)
        digest.update(b"git:")
        digest.update(self.url.encode("utf-8"))
        digest.update(b"@")
        digest.update(self.ref.encode("utf-8"))
        digest.update(b":")
        if self.subpath is not None:
            digest.update(str(self.subpath).encode("utf-8"))
        return digest.hexdigest()

    def _populate_cache(self, cache_dir: Path) -> None:
        """Clone the repository, strip `.git`, narrow by subpath, and cache."""
        if shutil.which("git") is None:
            msg = "GitSource requires the `git` CLI on PATH."
            raise RuntimeError(msg)
        with tempfile.TemporaryDirectory(prefix="rue-git-source-") as tmp:
            clone_target = Path(tmp, "checkout")
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    self.ref,
                    self.url,
                    str(clone_target),
                ],
                check=True,
                capture_output=True,
            )
            shutil.rmtree(clone_target / ".git", ignore_errors=True)
            if self.subpath is None:
                staged = clone_target
            else:
                staged = (clone_target / self.subpath).resolve()
                if not staged.exists():
                    msg = (
                        f"GitSource subpath '{self.subpath}' missing after "
                        f"clone of {self.url}@{self.ref}."
                    )
                    raise FileNotFoundError(msg)
            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            clone_tree(staged, cache_dir)


type Source = EnvSource


def empty() -> EmptySource:
    """Return an empty source."""
    return EmptySource()


def dir(path: str | Path) -> DirSource:  # noqa: A001 - public namespace name
    """Return a directory source rooted at `path`."""
    return DirSource(path=Path(path))


def git(
    url: str,
    *,
    ref: str,
    subpath: str | Path | None = None,
) -> GitSource:
    """Return a git source pinned to `ref`, optionally narrowed by subpath."""
    return GitSource(
        url=url,
        ref=ref,
        subpath=Path(subpath) if subpath is not None else None,
    )


def _install_into_dst(*, cache_dir: Path, dst: Path) -> None:
    empty_tree(dst)
    for child in cache_dir.iterdir():
        clone_tree(child, dst / child.name)


__all__ = [
    "DirSource",
    "EmptySource",
    "EnvSource",
    "GitSource",
    "Source",
    "dir",
    "empty",
    "git",
]
