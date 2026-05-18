"""Per-file diff views for checkpoint deltas."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import jsonpatch  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class FileDiff:
    """Per-file diff rendered as unified text, word DMP, or JSON Patch."""

    path: PurePosixPath
    before: bytes
    after: bytes

    @property
    def unified(self) -> str:
        """``difflib.unified_diff`` output as a single string."""
        label = str(self.path)
        return "".join(
            difflib.unified_diff(
                self.before.decode().splitlines(keepends=True),
                self.after.decode().splitlines(keepends=True),
                fromfile=label,
                tofile=label,
            )
        )

    @property
    def words(self) -> tuple[tuple[str, str], ...]:
        """Word-level diff as ``(op, text)`` tuples; op in ``{=, -, +}``."""
        before_tokens = re.findall(r"\s+|\S+", self.before.decode())
        after_tokens = re.findall(r"\s+|\S+", self.after.decode())
        out: list[tuple[str, str]] = []
        matcher = difflib.SequenceMatcher(
            a=before_tokens, b=after_tokens, autojunk=False
        )
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                out.append(("=", "".join(before_tokens[i1:i2])))
            elif op == "delete":
                out.append(("-", "".join(before_tokens[i1:i2])))
            elif op == "insert":
                out.append(("+", "".join(after_tokens[j1:j2])))
            else:  # replace
                out.append(("-", "".join(before_tokens[i1:i2])))
                out.append(("+", "".join(after_tokens[j1:j2])))
        return tuple(out)

    @property
    def json(self) -> list[dict[str, Any]]:
        """RFC 6902 JSON Patch between ``before`` and ``after``."""
        before = json.loads(self.before) if self.before else None
        after = json.loads(self.after) if self.after else None
        return list(jsonpatch.make_patch(before, after))


__all__ = [
    "FileDiff",
]
