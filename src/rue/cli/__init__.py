"""CLI module for Rue test runner."""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated, Optional
from uuid import UUID

from typer import Argument, Option, Typer
from rich.console import Console

from rue.cli.db import DatabaseCommands, db_app
from rue.config import load_config
from rue.testing.discovery import KeywordMatcher, TestCollector
from rue.testing.runner import Runner

app = Typer(name="rue", help="Rue AI Testing Framework", no_args_is_help=True)
app.add_typer(db_app, name="db")


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

    collector = TestCollector(
        include_tags, exclude_tags, keyword or runner_config.keyword
    )

    items = collector.collect(resolved_paths)

    runner = Runner(
        config=runner_config,
        fail_fast=fail_fast,
        capture_output=not show_output,
    )

    if runner_config.db_enabled and run_id and runner.run_id_exists(run_id):
        Console().print(f"[red]run_id '{run_id}' already exists[/red]")
        raise SystemExit(2)

    run = asyncio.run(runner.run(items=items, run_id=run_id))

    raise SystemExit(
        0 if run.result.failed == 0 and run.result.errors == 0 else 1
    )


def main() -> None:
    """Entry point for the rue CLI."""
    config = load_config()
    argv = [*config.addopts, *sys.argv[1:]] if config.addopts else sys.argv[1:]
    app(argv, standalone_mode=False)


__all__ = ["DatabaseCommands", "KeywordMatcher", "TestCollector", "main"]
