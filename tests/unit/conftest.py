"""Shared fixtures for unit tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rue.reports.console import ConsoleReporter
from rue.reports.otel import OtelReporter
from rue.reports.base import Reporter
from rue.storage.sqlite import SQLiteStore
from rue.storage.sqlite.migrations import MigrationRunner


def _reset_reporters() -> None:
    Reporter.REGISTRY.clear()
    ConsoleReporter()
    OtelReporter()


@pytest.fixture(autouse=True)
def clear_reporter_instances():
    _reset_reporters()
    yield
    _reset_reporters()


class NullReporter(Reporter):
    """Silent reporter for testing."""

    def configure(self, config) -> None:
        _ = config

    async def on_no_tests_found(self) -> None:
        pass

    async def on_collection_complete(self, items) -> None:
        pass

    async def on_test_start(self, item) -> None:
        pass

    async def on_test_complete(self, execution) -> None:
        pass

    async def on_run_complete(self, test_run) -> None:
        pass

    async def on_run_stopped_early(self, failure_count: int) -> None:
        pass


class TraceCollectorReporter(NullReporter):
    """Reporter that keeps collected OpenTelemetry sessions."""

    def __init__(self) -> None:
        self.sessions = []

    async def on_trace_collected(self, tracer, execution_id) -> None:
        _ = execution_id
        if tracer.completed_otel_trace_session is not None:
            self.sessions.append(tracer.completed_otel_trace_session)


@pytest.fixture
def null_reporter() -> NullReporter:
    """Provide a silent reporter for tests."""
    return NullReporter()


@pytest.fixture
def trace_reporter() -> TraceCollectorReporter:
    """Provide a reporter that collects completed OTEL sessions."""
    return TraceCollectorReporter()


@pytest.fixture
def sqlite_db_path(tmp_path: Path) -> Path:
    """Provide a per-test SQLite database path."""
    return tmp_path / "rue.db"


@pytest.fixture
def sqlite_store(sqlite_db_path: Path) -> SQLiteStore:
    """Provide a SQLite store bound to the test database path."""
    return SQLiteStore(sqlite_db_path)


@pytest.fixture
def migration_runner(sqlite_db_path: Path) -> MigrationRunner:
    """Provide a migration runner for the test database path."""
    return MigrationRunner(sqlite_db_path)


@pytest.fixture
def migrated_sqlite_db_path(migration_runner: MigrationRunner) -> Path:
    """Provide a migrated SQLite database path."""
    migration_runner.migrate()
    return migration_runner.path


@pytest.fixture
def mock_console() -> MagicMock:
    """Provide a mock console."""
    return MagicMock()
