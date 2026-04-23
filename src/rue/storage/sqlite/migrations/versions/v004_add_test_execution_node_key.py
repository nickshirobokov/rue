"""Persist stable execution tree keys for historical status lookups."""

import sqlite3


VERSION = 4


def up(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE test_executions ADD COLUMN node_key TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tests_node_key ON test_executions(node_key)"
    )
