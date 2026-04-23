"""CLI module for Rue test runner."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from tomlkit import parse, table
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import Table
from typer import Typer

from rue.cli.db import DatabaseCommands, db_app
from rue.cli.tests import TestSpecCollector, tests_app
from rue.config import load_config
from rue.testing.discovery import KeywordMatcher


app = Typer(name="rue", help="Rue AI Testing Framework", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(tests_app, name="tests")

_TomlTable = Table | OutOfOrderTableProxy


@app.command()
def init() -> None:
    """Register Rue's pytest plugin in pyproject.toml."""
    path = Path("pyproject.toml")
    if not path.is_file():
        Console().print(
            "[red]pyproject.toml not found in current directory[/red]"
        )
        raise SystemExit(1)
    doc = parse(path.read_text())
    project = doc.get("project")
    if not isinstance(project, _TomlTable):
        Console().print("[red]pyproject.toml has no [[project]] table[/red]")
        raise SystemExit(1)
    entry_points = project.get("entry-points")
    if entry_points is None:
        entry_points = table()
        project["entry-points"] = entry_points
    if not isinstance(entry_points, _TomlTable):
        Console().print("[red]project.entry-points must be a TOML table[/red]")
        raise SystemExit(1)
    pytest11 = entry_points.get("pytest11")
    if pytest11 is None:
        pytest11 = table()
        entry_points["pytest11"] = pytest11
    if not isinstance(pytest11, _TomlTable):
        Console().print(
            "[red]project.entry-points.pytest11 must be a TOML table[/red]"
        )
        raise SystemExit(1)
    if pytest11.get("rue") == "rue.pytest_plugin":
        Console().print(
            "[cyan]Rue pytest plugin is already installed "
            "(pytest11 entry rue → rue.pytest_plugin).[/cyan]"
        )
        return
    pytest11["rue"] = "rue.pytest_plugin"
    path.write_text(doc.as_string())
    Console().print(
        "[green]Registered pytest11 entry point "
        "rue → rue.pytest_plugin.[/green]\n"
        "Run [bold]uv sync[/bold] (or reinstall the project) "
        "so pytest picks it up."
    )


def main() -> None:
    """Entry point for the rue CLI."""
    config = load_config()
    argv = [*config.addopts, *sys.argv[1:]] if config.addopts else sys.argv[1:]
    app(argv)


__all__ = ["DatabaseCommands", "KeywordMatcher", "TestSpecCollector", "main"]
