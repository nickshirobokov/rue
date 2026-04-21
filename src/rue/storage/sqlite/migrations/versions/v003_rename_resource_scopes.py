"""Rename persisted resource scope strings (case/suite/session → test/module/process)."""

import json
import sqlite3

VERSION = 3

_SCOPE_MAP = {"case": "test", "suite": "module", "session": "process"}


def up(conn: sqlite3.Connection) -> None:
    for old, new in _SCOPE_MAP.items():
        conn.execute("UPDATE metrics SET scope = ? WHERE scope = ?", (new, old))
        conn.execute(
            "UPDATE metrics SET provider_scope = ? WHERE provider_scope = ?",
            (new, old),
        )
    rows = conn.execute(
        "SELECT rowid, depends_on_metrics_json FROM metrics "
        "WHERE depends_on_metrics_json IS NOT NULL"
    ).fetchall()
    for rowid, raw in rows:
        data = json.loads(raw)
        changed = False
        for item in data:
            s = item.get("scope")
            if s in _SCOPE_MAP:
                item["scope"] = _SCOPE_MAP[s]
                changed = True
        if changed:
            conn.execute(
                "UPDATE metrics SET depends_on_metrics_json = ? WHERE rowid = ?",
                (json.dumps(data), rowid),
            )
