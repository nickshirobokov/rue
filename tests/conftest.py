"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rue.events import RunEventsProcessor
from rue.storage import TursoRunStore
from tests.helpers import TraceCollectorProcessor


def _reset_processors() -> None:
    RunEventsProcessor.REGISTRY.clear()


@pytest.fixture(autouse=True)
def clear_processor_instances():
    _reset_processors()
    yield
    _reset_processors()


@pytest.fixture
def trace_processor() -> TraceCollectorProcessor:
    return TraceCollectorProcessor()


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "rue.turso.db"


@pytest.fixture
def turso_store(database_path: Path) -> TursoRunStore:
    store = TursoRunStore(database_path)
    store.initialize()
    return store


@pytest.fixture
def mock_console() -> MagicMock:
    return MagicMock()
