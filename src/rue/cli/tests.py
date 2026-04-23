"""Test management CLI commands."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional
from uuid import UUID

from click.core import Context
from rich.console import Console
from typer import Argument, Option, Typer
from typer.core import TyperGroup

import rue.reports.console as console_reports
import rue.reports.otel as otel_reports
from rue.config import load_config
from rue.reports.base import Reporter
from rue.storage import SQLiteStore
from rue.testing.discovery import TestLoader, TestSpecCollector
from rue.testing.runner import Runner


class DefaultCommandGroup(TyperGroup):
    """Route bare group invocations to the default subcommand."""

    default_command_name = "run"

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        if ctx.resilient_parsing:
            return super().parse_args(ctx, args)
        if args and args[0] in {"--help", "-h"}:
            return super().parse_args(ctx, args)
        if args and args[0] in self.commands:
            return super().parse_args(ctx, args)
        return super().parse_args(ctx, [self.default_command_name, *args])


tests_app = Typer(cls=DefaultCommandGroup, help="Test operations")


@tests_app.command()
def run(
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
    _ = console_reports, otel_reports
    if not runner_config.reporters:
        reporters = list(Reporter.REGISTRY.values())
    else:
        reporters = []
        for name in runner_config.reporters:
            if name not in Reporter.REGISTRY:
                available = ", ".join(sorted(Reporter.REGISTRY))
                msg = f"Unknown reporter: {name}. Available: {available}"
                raise ValueError(msg)
            reporters.append(Reporter.REGISTRY[name])
    store = (
        None
        if not runner_config.db_enabled
        else SQLiteStore(runner_config.resolved_db_path)
    )

    collection = collector.build_spec_collection(resolved_paths)
    items = TestLoader(collection.suite_root).load_from_collection(collection)

    if (
        run_id is not None
        and store is not None
        and store.get_run(run_id) is not None
    ):
        Console().print(f"[red]run_id '{run_id}' already exists[/red]")
        raise SystemExit(2)

    runner = Runner(
        config=runner_config,
        reporters=reporters,
        store=store,
        fail_fast=fail_fast,
        capture_output=not show_output,
    )

    run_result = asyncio.run(runner.run(items, run_id=run_id))

    raise SystemExit(
        0
        if run_result.result.failed == 0 and run_result.result.errors == 0
        else 1
    )


__all__ = ["TestSpecCollector", "tests_app"]
