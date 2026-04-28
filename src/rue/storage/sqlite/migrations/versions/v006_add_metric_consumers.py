"""Persist metric consumer specs."""

import sqlite3


VERSION = 6


def up(conn: sqlite3.Connection) -> None:
    """Add serialized consumer specs for metric metadata."""
    conn.execute("ALTER TABLE metrics ADD COLUMN consumers_json TEXT")
    for column in (
        "collected_from_tests_json",
        "collected_from_resources_json",
        "collected_from_cases_json",
        "collected_from_modules_json",
    ):
        conn.execute(f"ALTER TABLE metrics DROP COLUMN {column}")
