"""Database management CLI commands."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Optional

from typer import Option, Typer
from rich.console import Console

from rue.config import Config, load_config
from rue.storage.sqlite.migrations import MigrationRunner
from rue.storage.sqlite.store import MAX_STORED_RUNS

db_app = Typer(help="Database management commands")


class DatabaseCommands:
    """Encapsulates all `rue db` operations against a single database path."""

    def __init__(self, config: Config) -> None:
        self.console = Console()
        self.db_path = config.resolved_db_path

    def status(self) -> int:
        runner = MigrationRunner(self.db_path)
        current = runner.get_current_version()
        target = runner.get_target_version()
        pending = len(runner.get_pending_migrations())

        self.console.print(f"Database: {self.db_path}")
        self.console.print(f"Current version: {current}")
        self.console.print(f"Target version: {target}")
        self.console.print(f"Max stored runs: {MAX_STORED_RUNS}")

        if current == target:
            self.console.print("[green]Status: Up to date[/green]")
        elif current > target:
            self.console.print(
                "[red]Status: Database ahead of code (downgrade not supported)[/red]"
            )
        else:
            self.console.print(
                f"[yellow]Status: Migration required ({pending} pending)[/yellow]"
            )

        return 0

    def migrate(self, *, dry_run: bool = False) -> int:
        runner = MigrationRunner(self.db_path)

        if not runner.needs_migration():
            self.console.print("[green]Database is up to date.[/green]")
            return 0

        if not runner.can_migrate():
            self.console.print("[red]Migration not possible.[/red]")
            self.console.print("Run 'rue db backup' then 'rue db reset --yes'")
            return 1

        pending = runner.get_pending_migrations()

        if dry_run:
            self.console.print(
                f"[yellow]Dry run: {len(pending)} migration(s) would be applied:[/yellow]"
            )
            for migration in pending:
                self.console.print(
                    f"  - v{migration.version:03d}: {migration.name}"
                )
            return 0

        self.console.print(f"Applying {len(pending)} migration(s)...")
        runner.migrate()
        self.console.print(
            f"[green]Migrated to version {runner.get_target_version()}[/green]"
        )
        return 0

    def backup(self) -> int:
        if not self.db_path.exists():
            self.console.print(f"[red]Database not found: {self.db_path}[/red]")
            return 1

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.with_suffix(f".db.backup.{timestamp}")

        with (
            sqlite3.connect(self.db_path) as source,
            sqlite3.connect(backup_path) as dest,
        ):
            source.backup(dest)

        self.console.print(f"Backed up database to: {backup_path}")
        return 0

    def reset(self, *, confirmed: bool) -> int:
        if not confirmed:
            self.console.print(
                "[bold red]WARNING: This will DELETE all test run history.[/bold red]"
            )
            self.console.print()
            self.console.print(f"Database: {self.db_path}")
            if self.db_path.exists():
                size_mb = self.db_path.stat().st_size / (1024 * 1024)
                self.console.print(f"Size: {size_mb:.1f} MB")
            self.console.print()
            self.console.print("To proceed, run:")
            self.console.print("    rue db reset --yes")
            self.console.print()
            self.console.print("Consider backing up first:")
            self.console.print("    rue db backup")
            return 1

        if self.db_path.exists():
            self.db_path.unlink()
            for suffix in ("-wal", "-shm"):
                wal_file = self.db_path.with_name(self.db_path.name + suffix)
                if wal_file.exists():
                    wal_file.unlink()

        runner = MigrationRunner(self.db_path)
        runner.migrate()

        self.console.print(
            f"[green]Database reset complete: {self.db_path}[/green]"
        )
        self.console.print(f"Schema version: {runner.get_target_version()}")
        return 0


@db_app.command()
def status(
    db_path: Annotated[
        Optional[str], Option(help="Path to the Rue SQLite database")
    ] = None,
) -> None:
    """Show database schema version status."""
    raise SystemExit(
        DatabaseCommands(load_config().with_overrides(db_path=db_path)).status()
    )


@db_app.command()
def migrate(
    db_path: Annotated[
        Optional[str], Option(help="Path to the Rue SQLite database")
    ] = None,
    dry_run: Annotated[
        bool,
        Option("--dry-run", help="Show pending migrations without applying"),
    ] = False,
) -> None:
    """Run pending migrations."""
    raise SystemExit(
        DatabaseCommands(load_config().with_overrides(db_path=db_path)).migrate(
            dry_run=dry_run
        )
    )


@db_app.command()
def backup(
    db_path: Annotated[
        Optional[str], Option(help="Path to the Rue SQLite database")
    ] = None,
) -> None:
    """Create a backup of the database."""
    raise SystemExit(
        DatabaseCommands(load_config().with_overrides(db_path=db_path)).backup()
    )


@db_app.command()
def reset(
    db_path: Annotated[
        Optional[str], Option(help="Path to the Rue SQLite database")
    ] = None,
    yes: Annotated[
        bool,
        Option("--yes", help="Confirm destructive reset without prompting"),
    ] = False,
) -> None:
    """Delete and recreate the database."""
    raise SystemExit(
        DatabaseCommands(load_config().with_overrides(db_path=db_path)).reset(
            confirmed=yes
        )
    )
