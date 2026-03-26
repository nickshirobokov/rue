"""Rename tracing tables and columns to OpenTelemetry-specific names."""

import sqlite3


VERSION = 2


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def up(conn: sqlite3.Connection) -> None:
    """Rename trace schema objects to their OpenTelemetry-specific equivalents."""
    execution_columns = _column_names(conn, "test_executions")
    if (
        "trace_id" in execution_columns
        and "otel_trace_id" not in execution_columns
    ):
        conn.execute(
            "ALTER TABLE test_executions RENAME COLUMN trace_id TO otel_trace_id"
        )

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "trace_spans" in tables and "otel_spans" not in tables:
        conn.execute("ALTER TABLE trace_spans RENAME TO otel_spans")

    if "otel_spans" in {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }:
        otel_span_columns = _column_names(conn, "otel_spans")
        if (
            "trace_id" in otel_span_columns
            and "otel_trace_id" not in otel_span_columns
        ):
            conn.execute(
                "ALTER TABLE otel_spans RENAME COLUMN trace_id TO otel_trace_id"
            )

    conn.execute("DROP INDEX IF EXISTS idx_tests_trace")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tests_otel_trace "
        "ON test_executions(otel_trace_id)"
    )

    conn.execute("DROP INDEX IF EXISTS idx_trace_spans_run")
    conn.execute("DROP INDEX IF EXISTS idx_trace_spans_execution")
    conn.execute("DROP INDEX IF EXISTS idx_trace_spans_trace")
    conn.execute("DROP INDEX IF EXISTS idx_trace_spans_name")
    conn.execute("DROP INDEX IF EXISTS idx_otel_spans_run")
    conn.execute("DROP INDEX IF EXISTS idx_otel_spans_execution")
    conn.execute("DROP INDEX IF EXISTS idx_otel_spans_trace")
    conn.execute("DROP INDEX IF EXISTS idx_otel_spans_name")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_otel_spans_run ON otel_spans(run_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_otel_spans_execution "
        "ON otel_spans(test_execution_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_otel_spans_trace "
        "ON otel_spans(otel_trace_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_otel_spans_name ON otel_spans(name)"
    )
