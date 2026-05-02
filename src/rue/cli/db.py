"""Database management CLI commands."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from rich.console import Console
from typer import Option, Typer

from rue.config import Config, load_config
from rue.storage import DBManager
from rue.storage.manager import MAX_STORED_RUNS


db_app = Typer(help="Database management commands")


class DatabaseCommands:
    """Encapsulates all `rue db` operations against a single database path."""

    def __init__(self, config: Config) -> None:
        self.console = Console()
        self.db_path = config.db_path
        self.manager = DBManager(self.db_path)

    def status(self) -> int:
        """Print database schema status."""
        current = self.manager.get_current_version()
        target = self.manager.get_target_version()
        pending = len(self.manager.get_pending_migrations())

        self.console.print(f"Database: {self.db_path}")
        self.console.print(f"Current version: {current}")
        self.console.print(f"Target version: {target}")
        self.console.print(f"Max stored runs: {MAX_STORED_RUNS}")

        if current == target:
            self.console.print("[green]Status: Up to date[/green]")
        elif current > target:
            self.console.print(
                "[red]Status: Database ahead of code "
                "(downgrade not supported)[/red]"
            )
        else:
            self.console.print(
                "[yellow]Status: Migration required "
                f"({pending} pending)[/yellow]"
            )

        return 0

    def migrate(self, *, dry_run: bool = False) -> int:
        """Apply pending migrations."""
        if not self.manager.needs_migration():
            self.console.print("[green]Database is up to date.[/green]")
            return 0

        if not self.manager.can_migrate():
            self.console.print("[red]Migration not possible.[/red]")
            self.console.print("Run 'rue db backup' then 'rue db reset --yes'")
            return 1

        pending = self.manager.get_pending_migrations()

        if dry_run:
            self.console.print(
                "[yellow]Dry run: "
                f"{len(pending)} migration(s) would be applied:[/yellow]"
            )
            for migration in pending:
                self.console.print(
                    f"  - v{migration.version:03d}: {migration.name}"
                )
            return 0

        self.console.print(f"Applying {len(pending)} migration(s)...")
        self.manager.migrate()
        target = self.manager.get_target_version()
        self.console.print(f"[green]Migrated to version {target}[/green]")
        return 0

    def backup(self) -> int:
        """Create a timestamped database backup."""
        if not self.db_path.exists():
            self.console.print(f"[red]Database not found: {self.db_path}[/red]")
            return 1

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = self.db_path.with_suffix(f".db.backup.{timestamp}")

        self.manager.backup(backup_path)

        self.console.print(f"Backed up database to: {backup_path}")
        return 0

    def reset(self, *, confirmed: bool) -> int:
        """Delete and recreate the database after confirmation."""
        if not confirmed:
            self.console.print(
                "[bold red]WARNING: This will DELETE all test run "
                "history.[/bold red]"
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

        self.manager.reset()

        self.console.print(
            f"[green]Database reset complete: {self.db_path}[/green]"
        )
        self.console.print(
            f"Schema version: {self.manager.get_target_version()}"
        )
        return 0


@db_app.command()
def status(
    db_path: Annotated[
        str | None, Option(help="Path to the Rue SQLite database")
    ] = None,
) -> None:
    """Show database schema version status."""
    raise SystemExit(
        DatabaseCommands(load_config().with_overrides(db_path=db_path)).status()
    )


@db_app.command()
def migrate(
    db_path: Annotated[
        str | None, Option(help="Path to the Rue SQLite database")
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
        str | None, Option(help="Path to the Rue SQLite database")
    ] = None,
) -> None:
    """Create a backup of the database."""
    raise SystemExit(
        DatabaseCommands(load_config().with_overrides(db_path=db_path)).backup()
    )


@db_app.command()
def reset(
    db_path: Annotated[
        str | None, Option(help="Path to the Rue SQLite database")
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
