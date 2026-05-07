"""Unified `rue run` command."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from copy import deepcopy
from typing import Annotated
from uuid import UUID

from rich.console import Console
from typer import Option

from rue.cli.console import ConsoleReporter, ExperimentConsoleReporter
from rue.cli.errors import print_definition_errors
from rue.cli.experiments.render import experiment_renderer
from rue.cli.options import (
    KeywordOpt,
    SkipTagOpt,
    TagOpt,
    TestPathsArg,
    VerboseOpt,
    resolve_selection,
)
from rue.config import load_config
from rue.context.runtime import RunContext
from rue.events import SessionEventsReceiver
from rue.events.processor import RunEventsProcessor
from rue.events.receiver import RunEventsReceiver
from rue.experiments.runner import ExperimentRunner
from rue.resources import (
    DependencyResolver,
    registry as default_resource_registry,
)
from rue.storage import TursoRunRecorder, TursoRunStore
from rue.telemetry.otel import OtelReporter
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
    run_id: Annotated[
        UUID | None,
        Option("--run-id", help="UUID to assign to this test run"),
    ] = None,
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
    experiment: Annotated[
        bool,
        Option(
            "-exp",
            "--experiment",
            help="Parse and run experiment variants",
        ),
    ] = False,
) -> None:
    """Run rue tests, or experiment variants with -exp."""
    if experiment:
        match (run_id, maxfail):
            case (UUID(), _):
                Console().print("[red]--run-id cannot be used with -exp[/red]")
                raise SystemExit(2)
            case (_, int()):
                Console().print("[red]--maxfail cannot be used with -exp[/red]")
                raise SystemExit(2)
            case _:
                pass

    runner_config, collector, resolved_paths = resolve_selection(
        config=load_config(),
        paths=paths,
        keyword=keyword,
        tag=tag,
        skip_tag=skip_tag,
        verbose=verbose,
        quiet=quiet,
        maxfail=maxfail if maxfail and maxfail > 0 else None,
        fail_fast=fail_fast,
        concurrency=max(0, concurrency) if concurrency is not None else None,
        timeout=timeout if timeout and timeout > 0 else None,
        otel=otel,
        processors=processor if not experiment else [],
    )

    if experiment:
        runner_config = runner_config.with_overrides(
            maxfail=None,
            processors=[],
        )

    collection = collector.build_spec_collection(resolved_paths)
    try:
        load_collection = deepcopy(collection) if experiment else collection
        items = TestLoader(load_collection.suite_root).load_from_collection(
            load_collection
        )
    except TestDefinitionErrors as errors:
        print_definition_errors(errors)
        raise SystemExit(2) from errors

    if experiment:
        experiment_runner = ExperimentRunner(config=runner_config)
        experiments = experiment_runner.collect(collection)

        session_processors: list[RunEventsProcessor] = [
            ExperimentConsoleReporter(),
        ]
        for name in processor or []:
            if name not in RunEventsProcessor.REGISTRY:
                available = ", ".join(sorted(RunEventsProcessor.REGISTRY))
                raise ValueError(
                    f"Unknown processor: {name}. Available: {available}"
                )
            session_processors.append(RunEventsProcessor.REGISTRY[name])

        session = SessionEventsReceiver(session_processors)
        session.configure(runner_config)
        with ExitStack() as stack:
            stack.callback(session.close)
            results = asyncio.run(
                experiment_runner.run(
                    collection,
                    experiments,
                    session=session,
                )
            )
        console = Console()
        for renderable in experiment_renderer.render(
            results,
            runner_config.verbosity,
        ):
            console.print(renderable)
        raise SystemExit(0)

    store = TursoRunStore(runner_config.database_path)
    store.initialize()

    if run_id is not None and store.run_exists(run_id):
        Console().print(f"[red]run_id '{run_id}' already exists[/red]")
        raise SystemExit(2)

    processors: list[RunEventsProcessor] = [ConsoleReporter()]
    if runner_config.otel:
        processors.append(OtelReporter())
    for name in runner_config.processors:
        if name not in RunEventsProcessor.REGISTRY:
            available = ", ".join(sorted(RunEventsProcessor.REGISTRY))
            raise ValueError(
                f"Unknown processor: {name}. Available: {available}"
            )
        processors.append(RunEventsProcessor.REGISTRY[name])

    run_context = (
        RunContext(config=runner_config)
        if run_id is None
        else RunContext(config=runner_config, run_id=run_id)
    )
    events_receiver = RunEventsReceiver([*processors, TursoRunRecorder()])
    with run_context, events_receiver:
        run_result = asyncio.run(
            Runner().run(
                items,
                resolver=DependencyResolver(default_resource_registry),
            )
        )
    raise SystemExit(
        0
        if run_result.result.failed == 0
        and run_result.result.errors == 0
        else 1
    )


__all__ = ["run"]
