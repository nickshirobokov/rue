"""Turso run storage management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import turso

from rue.storage.schema import (
    MAX_STORED_RUNS,
    REQUIRED_CUSTOM_TYPES,
    SCHEMA,
    SCHEMA_VERSION,
    TURSO_FEATURES,
)


class TursoFeatureError(RuntimeError):
    """Raised when the configured Turso connection lacks required features."""


class TursoRunStore:
    """Owns the Turso database used for Rue run storage."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        features: str = TURSO_FEATURES,
    ) -> None:
        self.path = Path(".rue/rue.turso.db") if path is None else Path(path)
        self.features = features

    @contextmanager
    def connection(self) -> Iterator[turso.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    def connect(self) -> turso.Connection:
        conn = turso.connect(
            str(self.physical_path),
            experimental_features=self.features,
            isolation_level=None,
        )
        conn.row_factory = turso.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = mvcc").fetchone()
        return conn

    def initialize(self) -> None:
        with self.connection() as conn:
            self.probe(conn)
            conn.executescript(SCHEMA)
            conn.execute(
                """
                INSERT INTO rue_schema (id, version, features)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version = excluded.version,
                    features = excluded.features
                """,
                (SCHEMA_VERSION, self.features),
            )
            conn.commit()

    def probe(self, conn: turso.Connection) -> None:
        rows = conn.execute("PRAGMA list_types").fetchall()
        available = {str(row[0]).split("(", 1)[0] for row in rows}
        missing = REQUIRED_CUSTOM_TYPES - available
        if missing:
            names = ", ".join(sorted(missing))
            raise TursoFeatureError(
                f"Turso custom types are unavailable: {names}"
            )

    def exists(self) -> bool:
        return self.path.exists()

    def schema_version(self) -> int:
        if not self.exists():
            return 0
        with self.connection() as conn:
            row = conn.execute(
                "SELECT version FROM rue_schema WHERE id = 1"
            ).fetchone()
            return 0 if row is None else int(row["version"])

    def run_exists(self, run_id: UUID) -> bool:
        if not self.exists():
            return False
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
            return row is not None

    def run_count(self) -> int:
        if not self.exists():
            return 0
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()
            return int(row["count"])

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        """Return filesystem artifacts owned by this Turso database."""
        paths = [self.path, *self._sidecar_paths(self.path)]
        physical_path = self.physical_path
        if physical_path != self.path:
            paths.extend((physical_path, *self._sidecar_paths(physical_path)))
        return tuple(dict.fromkeys(paths))

    @property
    def physical_path(self) -> Path:
        """Return the path opened by Turso for the logical database path."""
        return self.path.resolve() if self.path.is_symlink() else self.path

    def _sidecar_paths(self, path: Path) -> tuple[Path, ...]:
        return (
            path.with_name(f"{path.name}-wal"),
            path.with_name(f"{path.name}-shm"),
            path.with_name(f"{path.name}-log"),
        )

    def reset(self) -> None:
        for path in self.artifact_paths:
            if path.exists() or path.is_symlink():
                path.unlink()
        target = self.path.with_name(f".{self.path.name}.{uuid4().hex}")
        self.path.symlink_to(target.name)
        self.initialize()


__all__ = [
    "MAX_STORED_RUNS",
    "SCHEMA_VERSION",
    "TURSO_FEATURES",
    "TursoFeatureError",
    "TursoRunStore",
]
