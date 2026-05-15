"""Environment source kinds and cached materialization."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rue.environment.storage import clone_tree, empty_tree


@dataclass(frozen=True, slots=True)
class EmptySource:
    """Marker for an empty environment root."""


@dataclass(frozen=True, slots=True)
class DirSource:
    """Materialize an environment from a host directory."""

    path: Path


@dataclass(frozen=True, slots=True)
class GitSource:
    """Materialize an environment from a remote git ref."""

    url: str
    ref: str
    subpath: Path | None = None


type Source = EmptySource | DirSource | GitSource


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


async def materialize(source: Source, *, cache_root: Path, dst: Path) -> None:
    """Materialize `source` into `dst`, populating `cache_root` if needed.

    `dst` must not exist (clone semantics); it is created as a fresh tree.
    Concurrent calls for the same fingerprint deduplicate via an `flock` on
    the cache lock file. The lock is acquired in a worker thread so other
    coroutines stay responsive.
    """
    fingerprint = await asyncio.to_thread(_fingerprint, source)
    cache_dir = cache_root / fingerprint
    cache_root.mkdir(parents=True, exist_ok=True)
    lock_path = cache_root / f"{fingerprint}.lock"

    await asyncio.to_thread(
        _ensure_cache_populated,
        source=source,
        cache_dir=cache_dir,
        lock_path=lock_path,
    )
    await asyncio.to_thread(_install_into_dst, cache_dir=cache_dir, dst=dst)


def _ensure_cache_populated(
    *,
    source: Source,
    cache_dir: Path,
    lock_path: Path,
) -> None:
    handle = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if cache_dir.exists() and any(cache_dir.iterdir()):
            return
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        _materialize_into_cache(source, cache_dir)
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def _materialize_into_cache(source: Source, cache_dir: Path) -> None:
    match source:
        case EmptySource():
            cache_dir.mkdir(parents=True)
        case DirSource(path=src):
            clone_tree(src.resolve(), cache_dir)
        case GitSource() as git_source:
            _materialize_git_into_cache(git_source, cache_dir)


def _materialize_git_into_cache(
    source: GitSource,
    cache_dir: Path,
) -> None:
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
                source.ref,
                source.url,
                str(clone_target),
            ],
            check=True,
            capture_output=True,
        )
        shutil.rmtree(clone_target / ".git", ignore_errors=True)
        if source.subpath is None:
            staged = clone_target
        else:
            staged = (clone_target / source.subpath).resolve()
            if not staged.exists():
                msg = (
                    f"GitSource subpath '{source.subpath}' missing after "
                    f"clone of {source.url}@{source.ref}."
                )
                raise FileNotFoundError(msg)
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        clone_tree(staged, cache_dir)


def _install_into_dst(*, cache_dir: Path, dst: Path) -> None:
    empty_tree(dst)
    for child in cache_dir.iterdir():
        clone_tree(child, dst / child.name)


def _fingerprint(source: Source) -> str:
    digest = hashlib.blake2b(digest_size=16)
    match source:
        case EmptySource():
            digest.update(b"empty:")
        case DirSource(path=path):
            real = str(path.resolve())
            digest.update(b"dir:")
            digest.update(real.encode("utf-8"))
            digest.update(b":")
            digest.update(_dir_signature(path).encode("utf-8"))
        case GitSource() as git_source:
            digest.update(b"git:")
            digest.update(git_source.url.encode("utf-8"))
            digest.update(b"@")
            digest.update(git_source.ref.encode("utf-8"))
            digest.update(b":")
            if git_source.subpath is not None:
                digest.update(str(git_source.subpath).encode("utf-8"))
    return digest.hexdigest()


def _dir_signature(path: Path) -> str:
    """Return a coarse mtime+size signature so edits invalidate the cache."""
    parts: list[str] = []
    real = path.resolve()
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


__all__ = [
    "DirSource",
    "EmptySource",
    "GitSource",
    "Source",
    "dir",
    "empty",
    "git",
    "materialize",
]
