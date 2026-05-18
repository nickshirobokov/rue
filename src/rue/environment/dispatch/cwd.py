"""Context-routed cwd helpers: getcwd, getcwdb, chdir, fchdir.

These wrappers update the active environment's tracked cwd
instead of the real process cwd, so concurrent envs in the same process
each see their own working directory.
"""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rue.environment.dispatch.base import install_dispatcher


if TYPE_CHECKING:
    from rue.environment.env import Environment


def _resolve_fd_to_path(fd: int) -> Path:
    """Read the real path that `fd` points at, platform-specifically.

    Linux: `/proc/self/fd/N` is a symlink to the actual path.
    macOS / BSD: `fcntl(F_GETPATH)` returns the path as bytes.
    """
    if sys.platform == "linux":
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    f_getpath = getattr(fcntl, "F_GETPATH", 50)
    buf = fcntl.fcntl(fd, f_getpath, b"\x00" * 1024)
    return Path(buf.rstrip(b"\x00").decode())


def _getcwd(env: Environment) -> str:
    return str(env.cwd)


def _getcwdb(env: Environment) -> bytes:
    return os.fsencode(str(env.cwd))


def _chdir(env: Environment, path: Any) -> None:
    if isinstance(path, int):
        env.cwd = _resolve_fd_to_path(path).resolve()
        return
    fspath = os.fspath(path)
    as_str = fspath.decode() if isinstance(fspath, bytes) else fspath
    if not os.path.isabs(as_str):
        as_str = os.path.join(str(env.cwd), as_str)
    # Resolve so subsequent `os.getcwd()` matches real-process semantics
    # (collapses `..` and `.`, follows symlinks).
    env.cwd = Path(as_str).resolve()


def _fchdir(env: Environment, fd: int) -> None:
    env.cwd = _resolve_fd_to_path(fd).resolve()


def install_cwd_dispatchers() -> None:
    """Wrap getcwd/getcwdb/chdir/fchdir to read/write the active env's cwd."""
    install_dispatcher(os, "getcwd", _getcwd)
    install_dispatcher(os, "getcwdb", _getcwdb)
    install_dispatcher(os, "chdir", _chdir)
    install_dispatcher(os, "fchdir", _fchdir)


__all__ = ["install_cwd_dispatchers"]
