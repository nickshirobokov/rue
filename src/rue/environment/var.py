"""Environment variable overlay and merged views."""

from __future__ import annotations

import errno
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any


class EnvVars(MutableMapping[str, str]):
    """Override layer over `os.environ` for an `Environment`.

    Stores user-supplied overrides and a set of "hidden" keys to mask.
    `view(base)` returns a live `MutableMapping` composed onto an arbitrary
    base mapping, used by the dispatcher routers and `Environment.exec`.
    """

    __slots__ = ("_hidden", "_overrides")

    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}
        self._hidden: set[str] = set()

    def __getitem__(self, key: str) -> str:
        """Return an overridden value, raising ``KeyError`` if not set."""
        self._check_key(key)
        if key in self._overrides:
            return self._overrides[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: str) -> None:
        """Set an override, dropping any prior ``unset`` flag."""
        self._check_key(key)
        self._check_value(value)
        self._overrides[key] = value
        self._hidden.discard(key)

    def __delitem__(self, key: str) -> None:
        """Drop an override; raise if the key was never overridden."""
        self._check_key(key)
        if key not in self._overrides:
            raise KeyError(key)
        del self._overrides[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate over override keys."""
        return iter(self._overrides)

    def __len__(self) -> int:
        """Return the override count."""
        return len(self._overrides)

    def unset(self, key: str) -> None:
        """Hide `key` from any base mapping during merging or activation."""
        self._check_key(key)
        self._hidden.add(key)
        self._overrides.pop(key, None)

    def restore(self, key: str) -> None:
        """Drop any override or hide flag for `key`."""
        self._check_key(key)
        self._overrides.pop(key, None)
        self._hidden.discard(key)

    def view(self, base: Mapping[str, str]) -> MergedVarsView:
        """Return a live `MutableMapping` of this overlay composed on `base`."""
        return MergedVarsView(self, base)

    @staticmethod
    def _check_key(key: str) -> None:
        if not isinstance(key, str):
            raise TypeError(f"str expected, not {type(key).__name__}")
        if key == "":
            raise OSError(errno.EINVAL, "Invalid argument")
        if "=" in key:
            raise ValueError("illegal environment variable name")
        if "\x00" in key:
            raise ValueError("embedded null byte")

    @staticmethod
    def _check_value(value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"str expected, not {type(value).__name__}")
        if "\x00" in value:
            raise ValueError("embedded null byte")

    @property
    def hidden(self) -> frozenset[str]:
        """Keys hidden from the base mapping."""
        return frozenset(self._hidden)

    @property
    def overrides(self) -> dict[str, str]:
        """A copy of the override map."""
        return dict(self._overrides)

    def __getstate__(self) -> dict[str, Any]:
        """Make the overlay safely picklable across subprocess transfers."""
        return {
            "overrides": dict(self._overrides),
            "hidden": list(self._hidden),
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore overlay state during unpickling."""
        self._overrides = {}
        self._hidden = set()
        for key, value in state["overrides"].items():
            self[key] = value
        for key in state["hidden"]:
            self.unset(key)


class MergedVarsView(MutableMapping[str, str]):
    """Live `EnvVars` overlay composed onto a base mapping.

    Reads consult the overlay first (returning an override or raising for
    a hidden key) and fall through to the base. Writes set on the
    overlay; deletes hide the key from any base value as well.
    """

    __slots__ = ("_base", "_overlay")

    def __init__(self, overlay: EnvVars, base: Mapping[str, str]) -> None:
        self._overlay = overlay
        self._base = base

    def __getitem__(self, key: str) -> str:
        """Return the merged value for ``key``."""
        EnvVars._check_key(key)
        if key in self._overlay._hidden:
            raise KeyError(key)
        if key in self._overlay._overrides:
            return self._overlay._overrides[key]
        return self._base[key]

    def __setitem__(self, key: str, value: str) -> None:
        """Set an override on the overlay."""
        self._overlay[key] = value

    def __delitem__(self, key: str) -> None:
        """Hide ``key`` from the merged view."""
        EnvVars._check_key(key)
        if key in self._overlay._hidden:
            raise KeyError(key)
        if key not in self._overlay._overrides and key not in self._base:
            raise KeyError(key)
        self._overlay.unset(key)

    def __iter__(self) -> Iterator[str]:
        """Iterate over visible keys in the merged view."""
        for key in self._base:
            if key in self._overlay._hidden or key in self._overlay._overrides:
                continue
            yield key
        yield from self._overlay._overrides

    def __len__(self) -> int:
        """Return the number of visible keys."""
        return sum(1 for _ in self)

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` is visible in the merged view."""
        if not isinstance(key, str):
            return False
        if key in self._overlay._hidden:
            return False
        if key in self._overlay._overrides:
            return True
        return key in self._base


__all__ = [
    "EnvVars",
    "MergedVarsView",
]
