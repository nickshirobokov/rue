"""Add richer metric provenance fields."""

import sqlite3


VERSION = 4


def up(conn: sqlite3.Connection) -> None:
    """Extend metrics with provider, module, and dependency provenance."""
    conn.execute("ALTER TABLE metrics ADD COLUMN collected_from_modules_json TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_name TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_scope TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_path TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN provider_dir TEXT")
    conn.execute("ALTER TABLE metrics ADD COLUMN depends_on_metrics_json TEXT")
    conn.execute(
        "UPDATE metrics SET provider_name = name, provider_scope = scope "
        "WHERE provider_name IS NULL"
    )
