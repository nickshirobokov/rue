"""Tests for rue db CLI commands."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from rue.cli.db import DatabaseCommands
from rue.config import Config


def _commands(db_path: Path, mock_console: MagicMock) -> DatabaseCommands:
    cmd = DatabaseCommands(Config(db_path=str(db_path)))
    cmd.console = mock_console
    return cmd


class TestDbStatus:
    """Tests for rue db status command."""

    def test_status_fresh_db(
        self, sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Status should show migration required for fresh DB."""
        result = _commands(sqlite_db_path, mock_console).status()

        assert result == 0
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Current version: 0" in c for c in calls)
        assert any("Migration required" in c for c in calls)

    def test_status_up_to_date(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Status should show up to date after migration."""
        result = _commands(migrated_sqlite_db_path, mock_console).status()

        assert result == 0
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Up to date" in c for c in calls)


class TestDbMigrate:
    """Tests for rue db migrate command."""

    def test_migrate_fresh_db(
        self, sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Migrate should create and populate fresh DB."""
        result = _commands(sqlite_db_path, mock_console).migrate()

        assert result == 0
        assert sqlite_db_path.exists()

        conn = sqlite3.connect(sqlite_db_path)
        version: int = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version > 0
        conn.close()

    def test_migrate_already_current(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Migrate should report up to date if no migrations needed."""
        result = _commands(migrated_sqlite_db_path, mock_console).migrate()

        assert result == 0
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("up to date" in c for c in calls)

    def test_migrate_dry_run_shows_pending(
        self, sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Dry run should show pending migrations without applying."""
        result = _commands(sqlite_db_path, mock_console).migrate(dry_run=True)

        assert result == 0
        assert not sqlite_db_path.exists()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Dry run" in c for c in calls)

    def test_migrate_dry_run_when_current(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Dry run on current DB should report up to date."""
        result = _commands(migrated_sqlite_db_path, mock_console).migrate(dry_run=True)

        assert result == 0
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("up to date" in c for c in calls)


class TestDbBackup:
    """Tests for rue db backup command."""

    def test_backup_creates_timestamped_copy(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Backup should create a timestamped copy of the database."""
        result = _commands(migrated_sqlite_db_path, mock_console).backup()

        assert result == 0
        backup_files = list(migrated_sqlite_db_path.parent.glob("*.backup.*"))
        assert len(backup_files) == 1

    def test_backup_missing_db_fails(
        self, sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Backup should fail if database doesn't exist."""
        result = _commands(sqlite_db_path, mock_console).backup()

        assert result == 1
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("not found" in c for c in calls)

    def test_backup_includes_wal_contents(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Backup should include uncommitted WAL data."""
        conn = sqlite3.connect(migrated_sqlite_db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "INSERT INTO runs (run_id, start_time, total_duration_ms, "
            "passed, failed, errors, skipped, xfailed, xpassed, total, stopped_early) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "wal-test-run",
                "2024-01-01T00:00:00",
                100.0,
                1,
                0,
                0,
                0,
                0,
                0,
                1,
                0,
            ),
        )
        conn.commit()
        conn.close()

        result = _commands(migrated_sqlite_db_path, mock_console).backup()
        assert result == 0

        backup_files = list(migrated_sqlite_db_path.parent.glob("*.backup.*"))
        assert len(backup_files) == 1

        backup_conn = sqlite3.connect(backup_files[0])
        rows = backup_conn.execute("SELECT run_id FROM runs").fetchall()
        assert ("wal-test-run",) in rows
        backup_conn.close()


class TestDbReset:
    """Tests for rue db reset command."""

    def test_reset_without_yes_shows_warning(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Reset without --yes should show warning and not delete."""
        result = _commands(migrated_sqlite_db_path, mock_console).reset(confirmed=False)

        assert result == 1
        assert migrated_sqlite_db_path.exists()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("WARNING" in c for c in calls)

    def test_reset_with_yes_recreates_db(
        self, migrated_sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Reset with --yes should delete and recreate database."""
        conn = sqlite3.connect(migrated_sqlite_db_path)
        conn.execute(
            "INSERT INTO runs (run_id, start_time, total_duration_ms, "
            "passed, failed, errors, skipped, xfailed, xpassed, total, stopped_early) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "2024-01-01T00:00:00", 100.0, 1, 0, 0, 0, 0, 0, 1, 0),
        )
        conn.commit()
        conn.close()

        result = _commands(migrated_sqlite_db_path, mock_console).reset(confirmed=True)

        assert result == 0
        assert migrated_sqlite_db_path.exists()

        conn = sqlite3.connect(migrated_sqlite_db_path)
        rows = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert rows == 0
        conn.close()

    def test_reset_fresh_db_creates_new(
        self, sqlite_db_path: Path, mock_console: MagicMock
    ) -> None:
        """Reset on non-existent DB should create new one."""
        result = _commands(sqlite_db_path, mock_console).reset(confirmed=True)

        assert result == 0
        assert sqlite_db_path.exists()
