"""Path-rebasing dispatchers for os/builtins/io path-taking functions.

Each entry in `_PATH_FUNCS` declares which positional/keyword arguments
of a function carry a path. Under an active env, those args are joined
with `env.cwd` if they're relative, then forwarded to the original.
"""

from __future__ import annotations

import builtins
import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rue.environment.dispatch.base import install_dispatcher


@dataclass(frozen=True, slots=True)
class _PathArg:
    """One path-typed argument of a wrapped function."""

    position: int
    name: str
    dir_fd_name: str | None = None
    fd_ok: bool = False
    optional: bool = False
    default: object = "."
    none_as_default: bool = False


@dataclass(frozen=True, slots=True)
class _PathSpec:
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


def _routed(orig: Callable[..., Any], spec: _PathSpec) -> Callable[..., Any]:
    """Build the env-active body: rebase declared path args, then call orig."""

    def routed(env: Any, *args: Any, **kwargs: Any) -> Any:
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

            if raw is None and parg.none_as_default:
                raw = parg.default
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

    return routed


def _install_rebase(owner: Any, name: str, spec: _PathSpec) -> None:
    """Install a path-arg rebase wrapper on `owner.name`, if it exists."""
    orig = getattr(owner, name, None)
    if orig is None:
        return
    install_dispatcher(owner, name, _routed(orig, spec))


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
_SINGLE_PATH_OPTIONAL_NONE_DEFAULT = _PathArg(
    position=0, name="path", optional=True, default=".", none_as_default=True
)


_PATH_FUNCS: dict[str, _PathSpec] = {
    # Metadata
    "stat": _PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "lstat": _PathSpec(args=(_SINGLE_PATH,)),
    "access": _PathSpec(args=(_SINGLE_PATH,)),
    # Enumeration
    "scandir": _PathSpec(args=(_SINGLE_PATH_OPTIONAL_NONE_DEFAULT,)),
    "listdir": _PathSpec(args=(_SINGLE_PATH_OPTIONAL_NONE_DEFAULT,)),
    # Mutation
    "mkdir": _PathSpec(args=(_SINGLE_PATH,)),
    "rmdir": _PathSpec(args=(_SINGLE_PATH,)),
    "unlink": _PathSpec(args=(_SINGLE_PATH,)),
    "remove": _PathSpec(args=(_SINGLE_PATH,)),
    "readlink": _PathSpec(args=(_SINGLE_PATH,)),
    "chmod": _PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "chown": _PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "utime": _PathSpec(args=(_SINGLE_PATH_FD_OK,)),
    "truncate": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD_FD_OK,)),
    # Two-path mutators
    "rename": _PathSpec(
        args=(
            _PathArg(position=0, name="src", dir_fd_name="src_dir_fd"),
            _PathArg(position=1, name="dst", dir_fd_name="dst_dir_fd"),
        )
    ),
    "replace": _PathSpec(
        args=(
            _PathArg(position=0, name="src", dir_fd_name="src_dir_fd"),
            _PathArg(position=1, name="dst", dir_fd_name="dst_dir_fd"),
        )
    ),
    "link": _PathSpec(
        args=(
            _PathArg(position=0, name="src", dir_fd_name="src_dir_fd"),
            _PathArg(position=1, name="dst", dir_fd_name="dst_dir_fd"),
        )
    ),
    # symlink: pos 0 is the link-target literal — do NOT rebase
    "symlink": _PathSpec(
        args=(_PathArg(position=1, name="dst", dir_fd_name="dir_fd"),)
    ),
    # Open primitive (os side)
    "open": _PathSpec(args=(_SINGLE_PATH,)),
    # Niche / platform-conditional
    "pathconf": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD_FD_OK,)),
    "statvfs": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD_FD_OK,)),
    "mkfifo": _PathSpec(args=(_SINGLE_PATH,)),
    "mknod": _PathSpec(args=(_SINGLE_PATH,)),
    "chflags": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "lchflags": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "getxattr": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "setxattr": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "listxattr": _PathSpec(
        args=(_SINGLE_PATH_OPTIONAL_NONE_DEFAULT,)
    ),
    "removexattr": _PathSpec(args=(_SINGLE_PATH_NO_DIR_FD,)),
    "fwalk": _PathSpec(
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


_OPEN_SPEC = _PathSpec(args=(_PathArg(position=0, name="file", fd_ok=True),))


def install_path_dispatchers() -> None:
    """Wrap path-taking chokepoints in `os`, plus `builtins.open`/`io.open`."""
    for name, spec in _PATH_FUNCS.items():
        _install_rebase(os, name, spec)
    # builtins.open and io.open reference the same callable in CPython but
    # are independent bindings; wrap each so neither leaks the unrouted form.
    _install_rebase(builtins, "open", _OPEN_SPEC)
    _install_rebase(io, "open", _OPEN_SPEC)


__all__ = ["install_path_dispatchers"]
