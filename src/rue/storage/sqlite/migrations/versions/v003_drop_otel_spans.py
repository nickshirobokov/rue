"""Drop deprecated OTEL trace storage."""

import sqlite3


VERSION = 3


def up(conn: sqlite3.Connection) -> None:
    """Remove deprecated OTEL schema from SQLite."""
    conn.execute("DROP INDEX IF EXISTS idx_tests_otel_trace")
    conn.execute("ALTER TABLE test_executions RENAME COLUMN id_suffix TO suffix")
    conn.execute("ALTER TABLE test_executions DROP COLUMN otel_trace_id")
    conn.execute("DROP TABLE otel_spans")
