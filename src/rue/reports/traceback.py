"""Utility for reconstructing Rich Tracebacks from stored JSON data."""

from __future__ import annotations

import json
import linecache

from rich.pretty import Node
from rich.traceback import Frame, Stack, Trace, Traceback


def rich_traceback_from_json(data: str, *, show_locals: bool = False) -> Traceback:
    """Reconstruct a Rich Traceback from stored JSON data.

    Rich's Traceback normally requires live exception objects. This function
    rebuilds a displayable Traceback from our stored JSON format by manually
    constructing the internal Trace -> Stack -> Frame hierarchy.
    """
    parsed = json.loads(data)
    frames = []
    for f in parsed["frames"]:
        locals_nodes: dict[str, Node] | None = None
        if show_locals and f.get("locals"):
            locals_nodes = {k: Node(value_repr=v) for k, v in f["locals"].items()}
        frames.append(
            Frame(
                filename=f["filename"],
                lineno=f["lineno"],
                name=f["name"],
                line=f.get("line")
                or linecache.getline(f["filename"], f["lineno"]).strip(),
                locals=locals_nodes,
            )
        )

    stack = Stack(
        exc_type=parsed["exc_type"],
        exc_value=parsed["exc_value"],
        frames=frames,
    )
    return Traceback(Trace(stacks=[stack]), show_locals=show_locals)
