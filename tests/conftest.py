"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rue.reports.base import Reporter
from rue.reports.console import ConsoleReporter
from rue.reports.otel import OtelReporter
from rue.storage.sqlite import SQLiteStore
from rue.storage.sqlite.migrations import MigrationRunner
from tests.helpers import NullReporter, TraceCollectorReporter


def _reset_reporters() -> None:
    Reporter.REGISTRY.clear()
    ConsoleReporter()
    OtelReporter()


@pytest.fixture(autouse=True)
def clear_reporter_instances():
    _reset_reporters()
    yield
    _reset_reporters()


@pytest.fixture
def null_reporter() -> NullReporter:
    return NullReporter()


@pytest.fixture
def trace_reporter() -> TraceCollectorReporter:
    return TraceCollectorReporter()


@pytest.fixture
def sqlite_db_path(tmp_path: Path) -> Path:
    return tmp_path / "rue.db"


@pytest.fixture
def sqlite_store(sqlite_db_path: Path) -> SQLiteStore:
    return SQLiteStore(sqlite_db_path)


@pytest.fixture
def migration_runner(sqlite_db_path: Path) -> MigrationRunner:
    return MigrationRunner(sqlite_db_path)


@pytest.fixture
def migrated_sqlite_db_path(migration_runner: MigrationRunner) -> Path:
    migration_runner.migrate()
    return migration_runner.path


@pytest.fixture
def mock_console() -> MagicMock:
    return MagicMock()
