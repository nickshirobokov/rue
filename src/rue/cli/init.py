"""`rue init` command."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from tomlkit import parse, table
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import Table


_TomlTable = Table | OutOfOrderTableProxy


def init() -> None:
    """Register Rue's pytest plugin in pyproject.toml."""
    console = Console()
    path = Path("pyproject.toml")
    if not path.is_file():
        console.print(
            "[red]pyproject.toml not found in current directory[/red]"
        )
        raise SystemExit(1)

    doc = parse(path.read_text())
    project = doc.get("project")
    if not isinstance(project, _TomlTable):
        console.print("[red]pyproject.toml has no [[project]] table[/red]")
        raise SystemExit(1)

    entry_points = project.get("entry-points")
    if entry_points is None:
        entry_points = table()
        project["entry-points"] = entry_points
    if not isinstance(entry_points, _TomlTable):
        console.print("[red]project.entry-points must be a TOML table[/red]")
        raise SystemExit(1)

    pytest11 = entry_points.get("pytest11")
    if pytest11 is None:
        pytest11 = table()
        entry_points["pytest11"] = pytest11
    if not isinstance(pytest11, _TomlTable):
        console.print(
            "[red]project.entry-points.pytest11 must be a TOML table[/red]"
        )
        raise SystemExit(1)

    if pytest11.get("rue") == "rue.pytest_plugin":
        console.print(
            "[cyan]Rue pytest plugin is already installed "
            "(pytest11 entry rue -> rue.pytest_plugin).[/cyan]"
        )
        return

    pytest11["rue"] = "rue.pytest_plugin"
    path.write_text(doc.as_string())
    console.print(
        "[green]Registered pytest11 entry point "
        "rue -> rue.pytest_plugin.[/green]\n"
        "Run [bold]uv sync[/bold] (or reinstall the project) "
        "so pytest picks it up."
    )


__all__ = ["init"]
