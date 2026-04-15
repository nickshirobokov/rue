"""CLI module for Rue test runner."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID

from rich.console import Console
from tomlkit import parse, table
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import Table
from typer import Argument, Option, Typer

from rue.cli.db import DatabaseCommands, db_app
from rue.config import load_config
from rue.testing.discovery import KeywordMatcher, TestLoader, TestSpecCollector
from rue.testing.runner import Runner


app = Typer(name="rue", help="Rue AI Testing Framework", no_args_is_help=True)
app.add_typer(db_app, name="db")

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
        Console().print(
            "[red]pyproject.toml has no [[project]] table[/red]"
        )
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


@app.command()
def test(
    paths: Annotated[
        Optional[list[str]], Argument(help="Test files or directories")
    ] = None,
    keyword: Annotated[
        Optional[str],
        Option("-k", "--keyword", help="Filter tests by keyword expression"),
    ] = None,
    tag: Annotated[
        Optional[list[str]],
        Option("-t", "--tag", help="Run tests with given tag"),
    ] = None,
    skip_tag: Annotated[
        Optional[list[str]],
        Option("--skip-tag", help="Skip tests that match this tag"),
    ] = None,
    maxfail: Annotated[
        Optional[int], Option("--maxfail", help="Stop after this many failures")
    ] = None,
    fail_fast: Annotated[
        bool,
        Option(
            "--fail-fast", help="Stop test after the first failed assertion"
        ),
    ] = False,
    concurrency: Annotated[
        Optional[int],
        Option(
            "--concurrency",
            help="Number of concurrent tests (default: 1, 0 for unlimited up to 10)",
        ),
    ] = None,
    timeout: Annotated[
        Optional[float],
        Option("--timeout", help="Global test run timeout in seconds"),
    ] = None,
    otel: Annotated[
        Optional[bool],
        Option("--otel/--no-otel", help="Enable/disable OpenTelemetry spans"),
    ] = None,
    quiet: Annotated[
        int, Option("-q", "--quiet", count=True, help="Reduce CLI output")
    ] = 0,
    verbose: Annotated[
        int, Option("-v", "--verbose", count=True, help="Increase CLI output")
    ] = 0,
    show_output: Annotated[
        bool,
        Option(
            "-s",
            "--show-output",
            help="Show SUT stdout/stderr live (still captured on the SUT)",
        ),
    ] = False,
    db_path: Annotated[
        Optional[str],
        Option("--db-path", help="Path to the Rue SQLite database"),
    ] = None,
    run_id: Annotated[
        Optional[UUID],
        Option("--run-id", help="UUID to assign to this test run"),
    ] = None,
    no_db: Annotated[
        bool, Option("--no-db", help="Disable writing run data to SQLite")
    ] = False,
    reporter: Annotated[
        Optional[list[str]],
        Option(
            "--reporter",
            help="Reporter to use (can be specified multiple times)",
        ),
    ] = None,
) -> None:
    """Run rue tests."""
    config = load_config()

    include_tags = [*config.include_tags, *(tag or [])]
    exclude_tags = [*config.exclude_tags, *(skip_tag or [])]
    resolved_paths = paths or config.test_paths
    resolved_verbosity = config.verbosity + verbose - quiet

    runner_config = config.with_overrides(
        keyword=keyword,
        maxfail=maxfail if maxfail and maxfail > 0 else None,
        concurrency=max(0, concurrency) if concurrency is not None else None,
        timeout=timeout if timeout and timeout > 0 else None,
        otel=otel,
        db_path=db_path,
        db_enabled=False if no_db else None,
        reporters=reporter,
        verbosity=resolved_verbosity,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
    )

    collector = TestSpecCollector(
        include_tags, exclude_tags, keyword or runner_config.keyword
    )

    runner = Runner(
        config=runner_config,
        fail_fast=fail_fast,
        capture_output=not show_output,
    )

    collection = collector.build_spec_collection(resolved_paths)
    items = TestLoader(collection.suite_root).load_from_collection(collection)

    if runner_config.db_enabled and run_id and runner.run_id_exists(run_id):
        Console().print(f"[red]run_id '{run_id}' already exists[/red]")
        raise SystemExit(2)

    run = asyncio.run(runner.run(items, run_id=run_id))

    raise SystemExit(
        0 if run.result.failed == 0 and run.result.errors == 0 else 1
    )


def main() -> None:
    """Entry point for the rue CLI."""
    config = load_config()
    argv = [*config.addopts, *sys.argv[1:]] if config.addopts else sys.argv[1:]
    app(argv, standalone_mode=False)


__all__ = ["DatabaseCommands", "KeywordMatcher", "TestSpecCollector", "main"]
