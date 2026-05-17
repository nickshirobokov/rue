"""Path-rebasing dispatchers for the os/builtins/io chokepoint set."""

from __future__ import annotations

import builtins
import io
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rue.environment.dispatch.current import current


@dataclass(frozen=True, slots=True)
class _PathArg:
    """One path-typed argument of a wrapped function."""

    position: int
    name: str
    dir_fd_name: str | None = None
    fd_ok: bool = False
    optional: bool = False
    default: object = "."


@dataclass(frozen=True, slots=True)
class PathSpec:
    """Declarative wrap rule for a path-taking function."""

    args: tuple[_PathArg, ...]


def _rebase(raw: Any, env: Any) -> Any:
    """Return `raw` rebased under `env.cwd` if it's a relative path."""
    fspath = os.fspath(raw)
    as_str = fspath.decode() if isinstance(fspath, bytes) else fspath
    if os.path.isabs(as_str):
        return raw
    rebased = os.path.join(str(env.cwd), as_str)
    return os.fsencode(rebased) if isinstance(fspath, bytes) else rebased


def _make_wrapper(orig: Callable[..., Any], spec: PathSpec) -> Callable[..., Any]:
    """Build a wrapper that rebases each declared path arg before calling orig."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        env = current()
        if env is None:
            return orig(*args, **kwargs)

        new_args = list(args)
        for parg in spec.args:
            if len(new_args) > parg.position:
                raw = new_args[parg.position]
                in_kwargs = False
            elif parg.name in kwargs:
                raw = kwargs[parg.name]
                in_kwargs = True
            elif parg.optional:
                raw = parg.default
                in_kwargs = True
            else:
                continue

            if parg.fd_ok and isinstance(raw, int):
                continue
            if (
                parg.dir_fd_name is not None
                and kwargs.get(parg.dir_fd_name) is not None
            ):
                continue
            if not isinstance(raw, (str, bytes, os.PathLike)):
                continue

            rebased = _rebase(raw, env)
            if in_kwargs:
                kwargs[parg.name] = rebased
            else:
                new_args[parg.position] = rebased

        return orig(*new_args, **kwargs)

    wrapper.__wrapped__ = orig  # type: ignore[attr-defined]
    wrapper.__name__ = getattr(orig, "__name__", "wrapper")
    wrapper.__qualname__ = getattr(orig, "__qualname__", wrapper.__name__)
    wrapper.__doc__ = getattr(orig, "__doc__", None)
    return wrapper


_SINGLE_PATH = _PathArg(position=0, name="path", dir_fd_name="dir_fd")
_SINGLE_PATH_FD_OK = _PathArg(
    position=0, name="path", dir_fd_name="dir_fd", fd_ok=True
)
_SINGLE_PATH_NO_DIR_FD = _PathArg(position=0, name="path")
_SINGLE_PATH_NO_DIR_FD_FD_OK = _PathArg(
    position=0, name="path", fd_ok=True
)
_SINGLE_PATH_OPTIONAL = _PathArg(
    position=0, name="path", optional=True, default="."
)


_PATH_FUNCS: dict[str, PathSpec] = {
    # Metadata
    "stat": PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "lstat": PathSpec(args=(_SINGLE_PATH,)),
    "access": PathSpec(args=(_SINGLE_PATH,)),
    # Enumeration
    "scandir": PathSpec(args=(_SINGLE_PATH_OPTIONAL,)),
    "listdir": PathSpec(args=(_SINGLE_PATH_OPTIONAL,)),
    # Mutation
    "mkdir": PathSpec(args=(_SINGLE_PATH,)),
    "rmdir": PathSpec(args=(_SINGLE_PATH,)),
    "unlink": PathSpec(args=(_SINGLE_PATH,)),
    "remove": PathSpec(args=(_SINGLE_PATH,)),
    "readlink": PathSpec(args=(_SINGLE_PATH,)),
    "chmod": PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "chown": PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "utime": PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "truncate": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD_FD_OK,)),
    # Two-path mutators
    "rename": PathSpec(
        args=(
            _PathArg(position=0, name="src", dir_fd_name="src_dir_fd"),
            _PathArg(position=1, name="dst", dir_fd_name="dst_dir_fd"),
        )
    ),
    "replace": PathSpec(
        args=(
            _PathArg(position=0, name="src", dir_fd_name="src_dir_fd"),
            _PathArg(position=1, name="dst", dir_fd_name="dst_dir_fd"),
        )
    ),
    "link": PathSpec(
        args=(
            _PathArg(position=0, name="src", dir_fd_name="src_dir_fd"),
            _PathArg(position=1, name="dst", dir_fd_name="dst_dir_fd"),
        )
    ),
    # symlink: pos 0 is the link-target literal — do NOT rebase
    "symlink": PathSpec(
        args=(_PathArg(position=1, name="dst", dir_fd_name="dir_fd"),)
    ),
    # Open primitive (os side)
    "open": PathSpec(args=(_SINGLE_PATH,)),
    # Niche / platform-conditional
    "pathconf": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD_FD_OK,)),
    "statvfs": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD_FD_OK,)),
    "mkfifo": PathSpec(args=(_SINGLE_PATH,)),
    "mknod": PathSpec(args=(_SINGLE_PATH,)),
    "chflags": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "lchflags": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "getxattr": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "setxattr": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "listxattr": PathSpec(
        args=(
            _PathArg(
                position=0,
                name="path",
                optional=True,
                default=".",
            ),
        )
    ),
    "removexattr": PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "fwalk": PathSpec(
        args=(
            _PathArg(
                position=0,
                name="top",
                dir_fd_name="dir_fd",
                optional=True,
                default=".",
            ),
        )
    ),
}


_BUILTINS_OPEN_SPEC = PathSpec(
    args=(_PathArg(position=0, name="file", fd_ok=True),)
)


_INSTALLED = False


def _install_open() -> None:
    """Wrap `builtins.open` and `io.open` (same callable, both bindings)."""
    orig_builtin = builtins.open
    wrapped = _make_wrapper(orig_builtin, _BUILTINS_OPEN_SPEC)
    builtins.open = wrapped  # type: ignore[assignment]
    if io.open is orig_builtin:
        io.open = wrapped  # type: ignore[assignment]
    else:
        io.open = _make_wrapper(io.open, _BUILTINS_OPEN_SPEC)  # type: ignore[assignment]


def _make_getcwd_wrapper(orig: Callable[[], str]) -> Callable[[], str]:
    def getcwd() -> str:
        env = current()
        if env is None:
            return orig()
        return str(env.cwd)

    getcwd.__wrapped__ = orig  # type: ignore[attr-defined]
    getcwd.__name__ = orig.__name__
    return getcwd


def _make_getcwdb_wrapper(orig: Callable[[], bytes]) -> Callable[[], bytes]:
    def getcwdb() -> bytes:
        env = current()
        if env is None:
            return orig()
        return os.fsencode(str(env.cwd))

    getcwdb.__wrapped__ = orig  # type: ignore[attr-defined]
    getcwdb.__name__ = orig.__name__
    return getcwdb


def _resolve_fd_to_path(fd: int) -> Path:
    """Read the real path the fd points at, platform-specifically.

    Linux: `/proc/self/fd/N` is a symlink to the actual path.
    macOS / BSD: `fcntl(F_GETPATH)` returns the path as bytes.
    """
    if sys.platform == "linux":
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    import fcntl

    f_getpath = getattr(fcntl, "F_GETPATH", 50)
    buf = fcntl.fcntl(fd, f_getpath, b"\x00" * 1024)
    if isinstance(buf, int):
        # Some platforms return an int; fall back to /dev/fd readlink.
        return Path(os.readlink(f"/dev/fd/{fd}"))
    return Path(buf.rstrip(b"\x00").decode())


def _check_inside_root(resolved: Path, env: Any) -> None:
    """Raise ValueError if `resolved` is not under `env.root`."""
    try:
        resolved.relative_to(env.root)
    except ValueError as exc:
        msg = (
            f"chdir target escapes environment root: "
            f"{resolved} is not inside {env.root}"
        )
        raise ValueError(msg) from exc


def _set_env_cwd(env: Any, resolved: Path) -> None:
    """Validate the target and update the env's tracked cwd."""
    _check_inside_root(resolved, env)
    if not resolved.is_dir():
        raise NotADirectoryError(str(resolved))
    env._cwd = resolved


def _make_chdir_wrapper(orig: Callable[[Any], None]) -> Callable[[Any], None]:
    def chdir(path: Any) -> None:
        env = current()
        if env is None:
            orig(path)
            return
        if isinstance(path, int):
            # fd → real path via /dev/fd. Real process cwd MUST NOT change
            # under an active env, so we never delegate to the original.
            _set_env_cwd(env, _resolve_fd_to_path(path).resolve())
            return
        rebased = _rebase(path, env)
        as_str = (
            rebased.decode() if isinstance(rebased, bytes) else str(rebased)
        )
        # Store the resolved, symlink-followed, absolute path so subsequent
        # `os.getcwd()` matches real-process semantics (collapses `..`/`.`).
        _set_env_cwd(env, Path(as_str).resolve())

    chdir.__wrapped__ = orig  # type: ignore[attr-defined]
    chdir.__name__ = orig.__name__
    return chdir


def _make_fchdir_wrapper(orig: Callable[[int], None]) -> Callable[[int], None]:
    def fchdir(fd: int) -> None:
        env = current()
        if env is None:
            orig(fd)
            return
        _set_env_cwd(env, _resolve_fd_to_path(fd).resolve())

    fchdir.__wrapped__ = orig  # type: ignore[attr-defined]
    fchdir.__name__ = orig.__name__
    return fchdir


def _make_putenv_wrapper(
    orig: Callable[[Any, Any], None],
) -> Callable[[Any, Any], None]:
    def putenv(key: Any, value: Any) -> None:
        env = current()
        if env is None:
            orig(key, value)
            return
        key_str = os.fsdecode(key) if isinstance(key, bytes) else key
        value_str = (
            os.fsdecode(value) if isinstance(value, bytes) else value
        )
        env.vars[key_str] = value_str

    putenv.__wrapped__ = orig  # type: ignore[attr-defined]
    putenv.__name__ = orig.__name__
    return putenv


def _make_unsetenv_wrapper(
    orig: Callable[[Any], None],
) -> Callable[[Any], None]:
    def unsetenv(key: Any) -> None:
        env = current()
        if env is None:
            orig(key)
            return
        key_str = os.fsdecode(key) if isinstance(key, bytes) else key
        env.vars.unset(key_str)

    unsetenv.__wrapped__ = orig  # type: ignore[attr-defined]
    unsetenv.__name__ = orig.__name__
    return unsetenv


def install_path_dispatchers() -> None:
    """Wrap every available chokepoint function in os/builtins/io."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    for name, spec in _PATH_FUNCS.items():
        orig = getattr(os, name, None)
        if orig is None:
            continue
        setattr(os, name, _make_wrapper(orig, spec))

    # os.remove is an alias for os.unlink — they share the same callable but
    # each module-level name is a separate binding. The loop above wrapped
    # each independently; verify by re-checking.

    if hasattr(os, "getcwd"):
        os.getcwd = _make_getcwd_wrapper(os.getcwd)  # type: ignore[assignment]
    if hasattr(os, "getcwdb"):
        os.getcwdb = _make_getcwdb_wrapper(os.getcwdb)  # type: ignore[assignment]
    if hasattr(os, "chdir"):
        os.chdir = _make_chdir_wrapper(os.chdir)  # type: ignore[assignment]
    if hasattr(os, "fchdir"):
        os.fchdir = _make_fchdir_wrapper(os.fchdir)  # type: ignore[assignment]
    if hasattr(os, "putenv"):
        os.putenv = _make_putenv_wrapper(os.putenv)  # type: ignore[assignment]
    if hasattr(os, "unsetenv"):
        os.unsetenv = _make_unsetenv_wrapper(os.unsetenv)  # type: ignore[assignment]

    _install_open()


__all__ = [
    "install_path_dispatchers",
]
