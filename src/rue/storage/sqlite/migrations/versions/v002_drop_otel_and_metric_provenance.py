"""Drop OTEL trace storage and add metric provenance."""

import sqlite3


VERSION = 2


def up(conn: sqlite3.Connection) -> None:
    """Remove OTEL schema and extend metrics with provenance fields."""
    conn.execute("DROP INDEX IF EXISTS idx_tests_otel_trace")
    conn.execute(
        "ALTER TABLE test_executions RENAME COLUMN id_suffix TO suffix"
    )
    conn.execute("ALTER TABLE test_executions DROP COLUMN otel_trace_id")
    conn.execute("DROP TABLE IF EXISTS otel_spans")

    conn.execute(
        "ALTER TABLE metrics ADD COLUMN collected_from_modules_json TEXT"
    )
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_name TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_scope TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_path TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_dir TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN depends_on_metrics_json TEXT")
    conn.execute(
        "UPDATE metrics SET provider_name = name, provider_scope = scope "
        "WHERE provider_name IS NULL"
    )
