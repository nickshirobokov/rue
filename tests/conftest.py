"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rue.events import RunEventsProcessor
from rue.reports.console import ConsoleReporter
from rue.reports.otel import OtelReporter
from rue.storage.sqlite import SQLiteStore
from rue.storage.sqlite.migrations import MigrationRunner
from tests.helpers import TraceCollectorProcessor


def _reset_processors() -> None:
    RunEventsProcessor.REGISTRY.clear()
    ConsoleReporter()
    OtelReporter()


@pytest.fixture(autouse=True)
def clear_processor_instances():
    _reset_processors()
    yield
    _reset_processors()


@pytest.fixture
def trace_processor() -> TraceCollectorProcessor:
    return TraceCollectorProcessor()


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
