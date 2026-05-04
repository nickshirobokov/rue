"""Tests for rue db CLI commands."""

from pathlib import Path
from unittest.mock import MagicMock

from rue.cli.db import DatabaseCommands
from rue.config import Config


def _commands(
    database_path: Path, mock_console: MagicMock
) -> DatabaseCommands:
    command = DatabaseCommands(Config(database_path=database_path))
    command.console = mock_console
    return command


def test_status_missing_database_does_not_create(
    database_path: Path, mock_console: MagicMock
) -> None:
    result = _commands(database_path, mock_console).status()

    assert result == 0
    assert not database_path.exists()
    calls = [str(call) for call in mock_console.print.call_args_list]
    assert any("Not initialized" in call for call in calls)


def test_init_creates_turso_database(
    database_path: Path, mock_console: MagicMock
) -> None:
    result = _commands(database_path, mock_console).init()

    assert result == 0
    assert database_path.exists()
    calls = [str(call) for call in mock_console.print.call_args_list]
    assert any("Database initialized" in call for call in calls)


def test_status_initialized_database_is_ready(
    database_path: Path, mock_console: MagicMock
) -> None:
    commands = _commands(database_path, mock_console)
    commands.init()
    mock_console.reset_mock()

    result = commands.status()

    assert result == 0
    calls = [str(call) for call in mock_console.print.call_args_list]
    assert any("Status: Ready" in call for call in calls)


def test_reset_without_yes_shows_warning(
    turso_store, mock_console: MagicMock
) -> None:
    result = _commands(turso_store.path, mock_console).reset(confirmed=False)

    assert result == 1
    assert turso_store.path.exists()
    calls = [str(call) for call in mock_console.print.call_args_list]
    assert any("WARNING" in call for call in calls)


def test_reset_with_yes_recreates_database(
    turso_store, mock_console: MagicMock
) -> None:
    with turso_store.connection() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, start_time, python_version, platform, hostname,
                working_directory, rue_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "00000000-0000-0000-0000-000000000001",
                "2024-01-01T00:00:00+00:00",
                "3.12.0",
                "darwin",
                "host",
                "/tmp/project",
                "1.0.0",
            ),
        )
        conn.commit()

    result = _commands(turso_store.path, mock_console).reset(confirmed=True)

    assert result == 0
    assert turso_store.path.exists()
    assert turso_store.run_count() == 0
