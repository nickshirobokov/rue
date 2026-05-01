"""`rue tests run` command."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from rich.console import Console
from typer import Option

import rue.reports.console as console_reports
import rue.reports.otel as otel_reports
from rue.cli.errors import print_definition_errors
from rue.cli.tests.options import (
    DBPathOpt,
    KeywordOpt,
    SkipTagOpt,
    TagOpt,
    TestPathsArg,
    VerboseOpt,
    resolve_selection,
)
from rue.config import load_config
from rue.context.runtime import RunContext
from rue.events.processor import RunEventsProcessor
from rue.events.receiver import RunEventsReceiver
from rue.resources import (
    DependencyResolver,
    registry as default_resource_registry,
)
from rue.storage import SQLiteStore
from rue.testing.discovery import TestDefinitionErrors, TestLoader
from rue.testing.runner import Runner


def run(
    paths: TestPathsArg = None,
    keyword: KeywordOpt = None,
    tag: TagOpt = None,
    skip_tag: SkipTagOpt = None,
    maxfail: Annotated[
        int | None,
        Option("--maxfail", help="Stop after this many failures"),
    ] = None,
    fail_fast: Annotated[
        bool | None,
        Option(
            "--fail-fast",
            help="Stop test after the first failed assertion",
        ),
    ] = None,
    concurrency: Annotated[
        int | None,
        Option(
            "--concurrency",
            help=(
                "Number of concurrent tests "
                "(default: 1, 0 for unlimited up to 10)"
            ),
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        Option("--timeout", help="Global test run timeout in seconds"),
    ] = None,
    otel: Annotated[
        bool | None,
        Option("--otel/--no-otel", help="Enable/disable OpenTelemetry spans"),
    ] = None,
    quiet: Annotated[
        int,
        Option("-q", "--quiet", count=True, help="Reduce CLI output"),
    ] = 0,
    verbose: VerboseOpt = 0,
    show_output: Annotated[
        bool,
        Option(
            "-s",
            "--show-output",
            help="Show SUT stdout/stderr live (still captured on the SUT)",
        ),
    ] = False,
    db_path: DBPathOpt = None,
    run_id: Annotated[
        UUID | None,
        Option("--run-id", help="UUID to assign to this test run"),
    ] = None,
    no_db: Annotated[
        bool,
        Option("--no-db", help="Disable writing run data to SQLite"),
    ] = False,
    processor: Annotated[
        list[str] | None,
        Option(
            "--processor",
            help=(
                "Run events processor to use "
                "(can be specified multiple times)"
            ),
        ),
    ] = None,
) -> None:
    """Run rue tests."""
    runner_config, collector, resolved_paths = resolve_selection(
        config=load_config(),
        paths=paths,
        keyword=keyword,
        tag=tag,
        skip_tag=skip_tag,
        verbose=verbose,
        quiet=quiet,
        db_path=db_path,
        maxfail=maxfail if maxfail and maxfail > 0 else None,
        fail_fast=fail_fast,
        concurrency=max(0, concurrency) if concurrency is not None else None,
        timeout=timeout if timeout and timeout > 0 else None,
        otel=otel,
        db_enabled=False if no_db else None,
        processors=processor,
    )

    _ = console_reports, otel_reports
    if not runner_config.processors:
        processors = list(RunEventsProcessor.REGISTRY.values())
    else:
        processors = []
        for name in runner_config.processors:
            if name not in RunEventsProcessor.REGISTRY:
                available = ", ".join(sorted(RunEventsProcessor.REGISTRY))
                msg = f"Unknown processor: {name}. Available: {available}"
                raise ValueError(msg)
            processors.append(RunEventsProcessor.REGISTRY[name])
    store = (
        None
        if not runner_config.db_enabled
        else SQLiteStore(runner_config.resolved_db_path)
    )

    collection = collector.build_spec_collection(resolved_paths)
    try:
        items = TestLoader(collection.suite_root).load_from_collection(
            collection
        )
    except TestDefinitionErrors as errors:
        print_definition_errors(errors)
        raise SystemExit(2) from errors

    if (
        run_id is not None
        and store is not None
        and store.get_run(run_id) is not None
    ):
        Console().print(f"[red]run_id '{run_id}' already exists[/red]")
        raise SystemExit(2)

    context = (
        RunContext(config=runner_config)
        if run_id is None
        else RunContext(config=runner_config, run_id=run_id)
    )
    with context, RunEventsReceiver(processors):
        runner = Runner(
            store=store,
            capture_output=not show_output,
        )
        run_result = asyncio.run(
            runner.run(
                items,
                resolver=DependencyResolver(default_resource_registry),
            )
        )
    raise SystemExit(
        0
        if run_result.result.failed == 0 and run_result.result.errors == 0
        else 1
    )


__all__ = ["Runner", "TestLoader", "load_config", "run"]
