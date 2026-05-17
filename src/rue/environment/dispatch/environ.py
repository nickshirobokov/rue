"""Context-routed `os.environ` / `os.environb` proxies."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, MutableMapping

from rue.environment.dispatch.current import current


_REAL_ENVIRON: MutableMapping[str, str] | None = None
_REAL_ENVIRONB: MutableMapping[bytes, bytes] | None = None


def real_environ() -> MutableMapping[str, str]:
    """Return the real `os.environ` captured before dispatch was installed."""
    if _REAL_ENVIRON is None:
        raise RuntimeError(
            "Environment dispatchers were not installed; "
            "real_environ() is unavailable."
        )
    return _REAL_ENVIRON


def real_environb() -> MutableMapping[bytes, bytes]:
    """Return the real `os.environb` captured before dispatch was installed."""
    if _REAL_ENVIRONB is None:
        raise RuntimeError(
            "Environment dispatchers were not installed; "
            "real_environb() is unavailable."
        )
    return _REAL_ENVIRONB


class _EnvironRouter(MutableMapping[str, str]):
    """Drop-in replacement for `os.environ` that routes through the active env.

    Reads consult the active env's overlay first, fall back to the real
    process environ unless the key is hidden. Writes/deletes mutate the
    overlay only; the real process environ is never touched while an env
    is active. With no active env, all operations pass through to the
    real environ.
    """

    __slots__ = ("_real",)

    def __init__(self, real: MutableMapping[str, str]) -> None:
        self._real = real

    def __getitem__(self, key: str) -> str:
        env = current()
        if env is None:
            return self._real[key]
        vars_ = env.vars
        if key in vars_._hidden:
            raise KeyError(key)
        overrides = vars_._overrides
        if key in overrides:
            return overrides[key]
        return self._real[key]

    def __setitem__(self, key: str, value: str) -> None:
        if not isinstance(key, str):
            raise TypeError(
                f"str expected, not {type(key).__name__}"
            )
        if not isinstance(value, str):
            raise TypeError(
                f"str expected, not {type(value).__name__}"
            )
        env = current()
        if env is None:
            self._real[key] = value
            return
        env.vars[key] = value

    def __delitem__(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError(
                f"str expected, not {type(key).__name__}"
            )
        env = current()
        if env is None:
            del self._real[key]
            return
        vars_ = env.vars
        if key in vars_._hidden:
            raise KeyError(key)
        if key not in vars_._overrides and key not in self._real:
            raise KeyError(key)
        vars_.unset(key)

    def __iter__(self) -> Iterator[str]:
        env = current()
        if env is None:
            return iter(self._real)
        return self._merged_iter(env)

    def _merged_iter(self, env: Any) -> Iterator[str]:
        hidden = env.vars._hidden
        overrides = env.vars._overrides
        for key in self._real:
            if key in hidden or key in overrides:
                continue
            yield key
        yield from overrides

    def __len__(self) -> int:
        env = current()
        if env is None:
            return len(self._real)
        hidden = env.vars._hidden
        overrides = env.vars._overrides
        count = sum(
            1
            for key in self._real
            if key not in hidden and key not in overrides
        )
        return count + len(overrides)

    def __contains__(self, key: object) -> bool:
        env = current()
        if env is None:
            return key in self._real
        if not isinstance(key, str):
            return False
        vars_ = env.vars
        if key in vars_._hidden:
            return False
        if key in vars_._overrides:
            return True
        return key in self._real

    def __repr__(self) -> str:
        return f"environ({self.copy()!r})"

    def copy(self) -> dict[str, str]:
        """Return a plain dict snapshot of the merged view."""
        env = current()
        if env is None:
            return dict(self._real)
        return env.vars.merged(self._real)

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

    Encodes/decodes keys and values via `os.fsencode` / `os.fsdecode`
    against the str-typed router so both views share the active env's
    overlay.
    """

    __slots__ = ("_str_router",)

    def __init__(self, str_router: _EnvironRouter) -> None:
        self._str_router = str_router

    def __getitem__(self, key: bytes) -> bytes:
        if not isinstance(key, bytes):
            raise TypeError(
                f"bytes expected, not {type(key).__name__}"
            )
        return os.fsencode(self._str_router[os.fsdecode(key)])

    def __setitem__(self, key: bytes, value: bytes) -> None:
        if not isinstance(key, bytes):
            raise TypeError(
                f"bytes expected, not {type(key).__name__}"
            )
        if not isinstance(value, bytes):
            raise TypeError(
                f"bytes expected, not {type(value).__name__}"
            )
        self._str_router[os.fsdecode(key)] = os.fsdecode(value)

    def __delitem__(self, key: bytes) -> None:
        if not isinstance(key, bytes):
            raise TypeError(
                f"bytes expected, not {type(key).__name__}"
            )
        del self._str_router[os.fsdecode(key)]

    def __iter__(self) -> Iterator[bytes]:
        for key in self._str_router:
            yield os.fsencode(key)

    def __len__(self) -> int:
        return len(self._str_router)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, bytes):
            return False
        return os.fsdecode(key) in self._str_router

    def __repr__(self) -> str:
        return f"environb({dict(self)!r})"

    def copy(self) -> dict[bytes, bytes]:
        """Return a plain dict snapshot of the merged view, bytes-typed."""
        return dict(self)


def install_environ_dispatchers() -> None:
    """Replace `os.environ` and `os.environb` with routing proxies."""
    global _REAL_ENVIRON, _REAL_ENVIRONB
    if _REAL_ENVIRON is not None:
        return
    _REAL_ENVIRON = os.environ
    str_router = _EnvironRouter(os.environ)
    os.environ = str_router  # type: ignore[assignment]
    if hasattr(os, "environb"):
        _REAL_ENVIRONB = os.environb
        os.environb = _EnvironbRouter(str_router)  # type: ignore[assignment]


__all__ = [
    "install_environ_dispatchers",
    "real_environ",
    "real_environb",
]
