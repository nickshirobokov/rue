"""Helpers for Rue span attributes."""

import os
from typing import Any


TRACE_REPR_MAX_LEN = 1000


def is_trace_content_enabled() -> bool:
    """Whether Rue should attach content-bearing span attributes."""
    return os.environ.get("RUE_TRACE_CONTENT", "true").lower() == "true"


def truncate_repr(value: Any, max_len: int = TRACE_REPR_MAX_LEN) -> str:
    """Truncate a repr string if too long."""
    try:
        rendered = repr(value)
        if len(rendered) <= max_len:
            return rendered
        return rendered[: max_len - 3] + "..."
    except Exception:
        return "<repr-failed>"
