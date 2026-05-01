"""Stop linking metric results to test executions."""

import sqlite3


VERSION = 7


def up(conn: sqlite3.Connection) -> None:
    """Drop metric execution attribution from SQLite storage."""
    conn.execute("DROP INDEX IF EXISTS idx_metrics_execution")
    conn.execute("ALTER TABLE metrics DROP COLUMN test_execution_id")
