"""Database management CLI commands."""

from __future__ import annotations

from typing import Annotated

from rich.console import Console
from typer import Option, Typer

from rue.config import Config, load_config
from rue.storage import MAX_STORED_RUNS, SCHEMA_VERSION, TursoRunStore


db_app = Typer(help="Database management commands")


class DatabaseCommands:
    """Encapsulates all `rue db` operations against a Turso database path."""

    def __init__(self, config: Config) -> None:
        self.console = Console()
        self.database_path = config.database_path
        self.store = TursoRunStore(self.database_path)

    def status(self) -> int:
        """Print database status without creating it."""
        current = self.store.schema_version()
        self.console.print(f"Database: {self.database_path}")
        self.console.print(f"Exists: {self.store.exists()}")
        self.console.print(f"Schema version: {current}")
        self.console.print(f"Target version: {SCHEMA_VERSION}")
        self.console.print(f"Max stored runs: {MAX_STORED_RUNS}")
        self.console.print(f"Stored runs: {self.store.run_count()}")

        if current == SCHEMA_VERSION:
            self.console.print("[green]Status: Ready[/green]")
        elif current == 0:
            self.console.print("[yellow]Status: Not initialized[/yellow]")
        else:
            self.console.print(
                "[red]Status: Unknown schema; run 'rue db reset --yes'[/red]"
            )

        return 0

    def init(self) -> int:
        """Create the Turso database schema."""
        self.store.initialize()
        self.console.print(
            f"[green]Database initialized: {self.database_path}[/green]"
        )
        self.console.print(f"Schema version: {SCHEMA_VERSION}")
        return 0

    def reset(self, *, confirmed: bool) -> int:
        """Delete and recreate the database after confirmation."""
        if not confirmed:
            self.console.print(
                "[bold red]WARNING: This will DELETE all test run "
                "history.[/bold red]"
            )
            self.console.print()
            self.console.print(f"Database: {self.database_path}")
            if self.database_path.exists():
                size_mb = self.database_path.stat().st_size / (1024 * 1024)
                self.console.print(f"Size: {size_mb:.1f} MB")
            self.console.print()
            self.console.print("To proceed, run:")
            self.console.print("    rue db reset --yes")
            return 1

        self.store.reset()

        self.console.print(
            f"[green]Database reset complete: {self.database_path}[/green]"
        )
        self.console.print(f"Schema version: {SCHEMA_VERSION}")
        return 0


@db_app.command()
def status(
    database_path: Annotated[
        str | None, Option("--database-path", help="Path to the Rue Turso database")
    ] = None,
) -> None:
    """Show database schema version status."""
    raise SystemExit(
        DatabaseCommands(
            load_config().with_overrides(database_path=database_path)
        ).status()
    )


@db_app.command()
def init(
    database_path: Annotated[
        str | None, Option("--database-path", help="Path to the Rue Turso database")
    ] = None,
) -> None:
    """Create the database schema."""
    raise SystemExit(
        DatabaseCommands(
            load_config().with_overrides(database_path=database_path)
        ).init()
    )


@db_app.command()
def reset(
    database_path: Annotated[
        str | None, Option("--database-path", help="Path to the Rue Turso database")
    ] = None,
    yes: Annotated[
        bool,
        Option("--yes", help="Confirm destructive reset without prompting"),
    ] = False,
) -> None:
    """Delete and recreate the database."""
    raise SystemExit(
        DatabaseCommands(
            load_config().with_overrides(database_path=database_path)
        ).reset(confirmed=yes)
    )
