"""Runtime helpers for rewritten assertions."""

from __future__ import annotations


def capture_var(values: dict[str, str], name: str, value: object) -> object:
    """Capture a variable's value and store it in a dictionary."""
    values[name] = repr(value)
    return value
