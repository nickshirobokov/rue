"""Context-routed `os.environ` / `os.environb` / `putenv` / `unsetenv`."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, MutableMapping
from typing import TYPE_CHECKING

from rue.environment.dispatch.current import active, install_dispatcher


if TYPE_CHECKING:
    from rue.environment.runtime import Environment


_REAL_ENVIRON: MutableMapping[str, str] = os.environ
_REAL_ENVIRONB: MutableMapping[bytes, bytes] | None = getattr(
    os, "environb", None
)


def real_environ() -> MutableMapping[str, str]:
    """Return the real process `os.environ`, captured before install."""
    return _REAL_ENVIRON


def real_environb() -> MutableMapping[bytes, bytes]:
    """Return the real process `os.environb`, captured before install."""
    if _REAL_ENVIRONB is None:
        raise AttributeError("os.environb is not available on this platform")
    return _REAL_ENVIRONB


def _check_bytes(value: object) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"bytes expected, not {type(value).__name__}")


class _EnvironRouter(MutableMapping[str, str]):
    """Drop-in `os.environ` that routes through the active env's overlay.

    With no active env, all operations pass through to the real environ.
    With an active env, the active env's `vars` overlay is composed onto
    the real environ as a live `MergedView` — reads, writes, and deletes
    all flow through that view.
    """

    __slots__ = ("_real",)

    def __init__(self, real: MutableMapping[str, str]) -> None:
        self._real = real

    def _target(self) -> MutableMapping[str, str]:
        env = active()
        return env.vars.view(self._real) if env is not None else self._real

    def __getitem__(self, key: str) -> str:
        return self._target()[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._target()[key] = value

    def __delitem__(self, key: str) -> None:
        del self._target()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._target())

    def __len__(self) -> int:
        return len(self._target())

    def __contains__(self, key: object) -> bool:
        return key in self._target()

    def __repr__(self) -> str:
        return f"environ({self.copy()!r})"

    def copy(self) -> dict[str, str]:
        """Return a plain dict snapshot of the active view."""
        return dict(self._target())

    def __or__(self, other: Mapping[str, str]) -> dict[str, str]:
        merged = self.copy()
        merged.update(other)
        return merged

    def __ror__(self, other: Mapping[str, str]) -> dict[str, str]:
        merged = dict(other)
        merged.update(self.copy())
        return merged

    def __ior__(self, other: Mapping[str, str]) -> _EnvironRouter:
        for key, value in other.items():
            self[key] = value
        return self


class _EnvironbRouter(MutableMapping[bytes, bytes]):
    """Bytes view over `_EnvironRouter`, mirroring `os.environb`.

    Encodes/decodes via `os.fsencode` / `os.fsdecode` against the
    str-typed router so both views share the active env's overlay.
    """

    __slots__ = ("_str_router",)

    def __init__(self, str_router: _EnvironRouter) -> None:
        self._str_router = str_router

    def __getitem__(self, key: bytes) -> bytes:
        _check_bytes(key)
        return os.fsencode(self._str_router[os.fsdecode(key)])

    def __setitem__(self, key: bytes, value: bytes) -> None:
        _check_bytes(key)
        _check_bytes(value)
        self._str_router[os.fsdecode(key)] = os.fsdecode(value)

    def __delitem__(self, key: bytes) -> None:
        _check_bytes(key)
        del self._str_router[os.fsdecode(key)]

    def __iter__(self) -> Iterator[bytes]:
        for key in self._str_router:
            yield os.fsencode(key)

    def __len__(self) -> int:
        return len(self._str_router)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, bytes) and os.fsdecode(key) in self._str_router

    def __repr__(self) -> str:
        return f"environb({dict(self)!r})"

    def copy(self) -> dict[bytes, bytes]:
        """Return a plain dict snapshot of the merged view, bytes-typed."""
        return dict(self)


def _putenv(env: Environment, key: str | bytes, value: str | bytes) -> None:
    key_str = os.fsdecode(key) if isinstance(key, bytes) else key
    value_str = os.fsdecode(value) if isinstance(value, bytes) else value
    env.vars[key_str] = value_str


def _unsetenv(env: Environment, key: str | bytes) -> None:
    key_str = os.fsdecode(key) if isinstance(key, bytes) else key
    env.vars.unset(key_str)


def install_environ_dispatchers() -> None:
    """Replace `os.environ`, `os.environb`, `os.putenv`, `os.unsetenv`."""
    str_router = _EnvironRouter(_REAL_ENVIRON)
    setattr(os, "environ", str_router)  # noqa: B010
    if _REAL_ENVIRONB is not None:
        setattr(os, "environb", _EnvironbRouter(str_router))  # noqa: B010
    install_dispatcher(os, "putenv", _putenv)
    install_dispatcher(os, "unsetenv", _unsetenv)


__all__ = [
    "install_environ_dispatchers",
    "real_environ",
    "real_environb",
]
