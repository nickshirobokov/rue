"""Tests for MigrationRunner."""

import sqlite3
from pathlib import Path

import pytest

from rue.storage.sqlite.migrations import MigrationConfigError, MigrationRunner
from rue.storage.sqlite.migrations.runner import Migration


class TestMigrationRunner:
    """Tests for migration runner functionality."""

    def test_fresh_db_runs_all_migrations(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """Fresh database should run all migrations."""
        migration_runner.migrate()

        assert sqlite_db_path.exists()
        conn = sqlite3.connect(sqlite_db_path)
        version: int = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == migration_runner.get_target_version()

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "runs" in table_names
        assert "test_executions" in table_names
        conn.close()

    def test_existing_db_applies_pending_migrations(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """Existing database should only apply pending migrations."""
        migration_runner.migrate()

        initial_version = migration_runner.get_current_version()
        runner2 = MigrationRunner(sqlite_db_path)
        assert not runner2.needs_migration()
        assert runner2.get_current_version() == initial_version

    def test_needs_migration_returns_false_when_current(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """needs_migration returns False when DB is up to date."""
        migration_runner.migrate()

        runner2 = MigrationRunner(sqlite_db_path)
        assert not runner2.needs_migration()

    def test_can_migrate_returns_false_for_downgrade(
        self, sqlite_db_path: Path
    ) -> None:
        """can_migrate returns False when DB version is ahead of code."""
        conn = sqlite3.connect(sqlite_db_path)
        conn.execute("PRAGMA user_version = 999")
        conn.commit()
        conn.close()

        runner = MigrationRunner(sqlite_db_path)
        assert not runner.can_migrate()

    def test_get_current_version_fresh_db(self, sqlite_db_path: Path) -> None:
        """Fresh DB should have version 0."""
        runner = MigrationRunner(sqlite_db_path)
        assert runner.get_current_version() == 0

    def test_get_pending_migrations(
        self, migration_runner: MigrationRunner
    ) -> None:
        """Should return list of migrations to apply."""
        pending = migration_runner.get_pending_migrations()
        assert len(pending) > 0
        assert all(isinstance(m, Migration) for m in pending)

    def test_data_preserved_across_migration(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """Core value test: existing data survives schema migration."""
        migration_runner.migrate()

        conn = sqlite3.connect(sqlite_db_path)
        conn.execute(
            "INSERT INTO runs (run_id, start_time, total_duration_ms, "
            "passed, failed, errors, skipped, xfailed, xpassed, total, stopped_early) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "2024-01-01T00:00:00", 100.0, 1, 0, 0, 0, 0, 0, 1, 0),
        )
        conn.execute(
            "INSERT INTO runs (run_id, start_time, total_duration_ms, "
            "passed, failed, errors, skipped, xfailed, xpassed, total, stopped_early) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-2", "2024-01-02T00:00:00", 200.0, 2, 0, 0, 0, 0, 0, 2, 0),
        )
        conn.commit()
        conn.close()

        runner2 = MigrationRunner(sqlite_db_path)
        assert not runner2.needs_migration()

        conn = sqlite3.connect(sqlite_db_path)
        rows = conn.execute(
            "SELECT run_id FROM runs ORDER BY run_id"
        ).fetchall()
        assert [r[0] for r in rows] == ["run-1", "run-2"]
        conn.close()

    def test_migrations_drop_otel_trace_storage_and_preserve_existing_data(
        self, sqlite_db_path: Path
    ) -> None:
        """Migrating from v2 should remove deprecated OTEL storage without touching run data."""
        full_runner = MigrationRunner(sqlite_db_path)
        legacy_runner = MigrationRunner.__new__(MigrationRunner)
        legacy_runner.path = sqlite_db_path
        legacy_runner._migrations = full_runner._migrations[:2]
        legacy_runner.migrate()

        conn = sqlite3.connect(sqlite_db_path)
        conn.execute(
            "INSERT INTO runs (run_id, start_time, total_duration_ms, "
            "passed, failed, errors, skipped, xfailed, xpassed, total, stopped_early) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "2024-01-01T00:00:00", 100.0, 1, 0, 0, 0, 0, 0, 1, 0),
        )
        conn.execute(
            "INSERT INTO test_executions ("
            "execution_id, run_id, parent_id, test_name, file_path, class_name, "
            "case_id, id_suffix, otel_trace_id, tags_json, skip_reason, xfail_reason, "
            "status, duration_ms, error_message, error_traceback"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "exec-1",
                "run-1",
                None,
                "test_sample",
                "tests/test_sample.py",
                None,
                None,
                None,
                "trace-1",
                None,
                None,
                None,
                "passed",
                10.0,
                None,
                None,
            ),
        )
        conn.execute(
            "INSERT INTO otel_spans ("
            "run_id, test_execution_id, otel_trace_id, span_id, parent_span_id, name, "
            "start_time_ns, end_time_ns, duration_ms, span_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "exec-1",
                "trace-1",
                "span-1",
                None,
                "test.test_sample",
                1,
                2,
                0.001,
                "{}",
            ),
        )
        conn.commit()
        conn.close()

        full_runner.migrate()

        conn = sqlite3.connect(sqlite_db_path)
        version: int = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        execution_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(test_executions)"
            ).fetchall()
        }
        rows = conn.execute("SELECT run_id FROM runs").fetchall()

        assert version == full_runner.get_target_version()
        assert "otel_spans" not in {table[0] for table in tables}
        assert "suffix" in execution_columns
        assert "id_suffix" not in execution_columns
        assert "otel_trace_id" not in execution_columns
        assert rows == [("run-1",)]
        conn.close()

    def test_injected_migration_applies_successfully(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """Injected migration should apply and bump schema version."""
        migration_runner.migrate()
        original_version = migration_runner.get_current_version()

        def add_dummy_table(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE dummy_migration (id INTEGER)")

        dummy_migration = Migration(
            version=original_version + 1,
            name="dummy",
            up=add_dummy_table,
        )

        runner2 = MigrationRunner.__new__(MigrationRunner)
        runner2.path = sqlite_db_path
        runner2._migrations = migration_runner._migrations + [dummy_migration]

        runner2.migrate()

        conn = sqlite3.connect(sqlite_db_path)
        version: int = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == original_version + 1

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dummy_migration'"
        ).fetchall()
        assert len(tables) == 1
        conn.close()

    def test_corrupted_db_no_user_version(self, sqlite_db_path: Path) -> None:
        """DB exists but has no tables - should still work."""
        conn = sqlite3.connect(sqlite_db_path)
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.commit()
        conn.close()

        runner = MigrationRunner(sqlite_db_path)
        assert runner.get_current_version() == 0
        runner.migrate()
        assert runner.get_current_version() == runner.get_target_version()


class TestMigrationFailure:
    """Tests for migration failure scenarios."""

    def test_failed_migration_rolls_back(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """If migration.up() raises, all pending migrations roll back."""
        migration_runner.migrate()
        original_version = migration_runner.get_current_version()

        def failing_up(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE new_table (id INTEGER)")
            raise RuntimeError("Simulated failure")

        bad_migration = Migration(
            version=original_version + 1, name="bad", up=failing_up
        )

        runner2 = MigrationRunner.__new__(MigrationRunner)
        runner2.path = sqlite_db_path
        runner2._migrations = migration_runner._migrations + [bad_migration]

        with pytest.raises(Exception, match="Simulated failure"):
            runner2.migrate()

        conn = sqlite3.connect(sqlite_db_path)
        version: int = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == original_version

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='new_table'"
        ).fetchall()
        assert len(tables) == 0
        conn.close()


class TestMigrationValidation:
    """Tests for migration file validation."""

    def test_version_gap_raises_config_error(
        self, sqlite_db_path: Path
    ) -> None:
        """Gap in version numbers should raise MigrationConfigError."""
        migrations = [
            Migration(version=1, name="v001", up=lambda conn: None),
            Migration(version=3, name="v003", up=lambda conn: None),
        ]

        runner = MigrationRunner.__new__(MigrationRunner)
        runner.path = sqlite_db_path
        runner._migrations = []

        with pytest.raises(MigrationConfigError, match="version gap"):
            runner._validate_migrations(migrations)

    def test_duplicate_version_raises_config_error(
        self, sqlite_db_path: Path
    ) -> None:
        """Duplicate versions should raise MigrationConfigError."""
        migrations = [
            Migration(version=1, name="v001_a", up=lambda conn: None),
            Migration(version=2, name="v002", up=lambda conn: None),
            Migration(version=2, name="v002_dup", up=lambda conn: None),
        ]

        runner = MigrationRunner.__new__(MigrationRunner)
        runner.path = sqlite_db_path
        runner._migrations = []

        with pytest.raises(MigrationConfigError, match="Duplicate"):
            runner._validate_migrations(migrations)

    def test_no_migrations_raises_config_error(
        self, sqlite_db_path: Path
    ) -> None:
        """Empty migrations list should raise MigrationConfigError."""
        runner = MigrationRunner.__new__(MigrationRunner)
        runner.path = sqlite_db_path
        runner._migrations = []

        with pytest.raises(MigrationConfigError):
            runner._validate_migrations([])

    def test_migrations_not_starting_at_1_raises_error(
        self, sqlite_db_path: Path
    ) -> None:
        """Migrations must start at version 1."""
        migrations = [
            Migration(version=2, name="v002", up=lambda conn: None),
        ]

        runner = MigrationRunner.__new__(MigrationRunner)
        runner.path = sqlite_db_path
        runner._migrations = []

        with pytest.raises(MigrationConfigError, match="start at version 1"):
            runner._validate_migrations(migrations)


class TestMigrationVersions:
    """Validate actual migration files are correctly structured."""

    def test_all_migrations_have_version(self) -> None:
        """All migration files should have VERSION constant."""

        runner = MigrationRunner.__new__(MigrationRunner)
        runner.path = Path("/tmp/unused.db")
        migrations = runner._discover_migrations()

        assert len(migrations) > 0
        for m in migrations:
            assert m.version > 0

    def test_versions_are_sequential(self) -> None:
        """Migration versions should be sequential starting from 1."""
        runner = MigrationRunner.__new__(MigrationRunner)
        runner.path = Path("/tmp/unused.db")
        migrations = runner._discover_migrations()

        versions = [m.version for m in migrations]
        expected = list(range(1, len(versions) + 1))
        assert versions == expected

    def test_initial_migration_creates_all_tables(
        self, sqlite_db_path: Path, migration_runner: MigrationRunner
    ) -> None:
        """Initial migration should create all required tables."""
        migration_runner.migrate()

        conn = sqlite3.connect(sqlite_db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        expected_tables = {
            "runs",
            "test_executions",
            "metrics",
            "assertions",
            "predicates",
        }
        assert expected_tables.issubset(table_names)
        assert "otel_spans" not in table_names
        conn.close()
