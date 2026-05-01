"""Drop deprecated test execution node keys."""

import sqlite3


VERSION = 8


def up(conn: sqlite3.Connection) -> None:
    """Remove node-key storage from test executions."""
    conn.execute("DROP INDEX IF EXISTS idx_tests_node_key")
    conn.execute("ALTER TABLE test_executions DROP COLUMN node_key")
