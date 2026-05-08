"""Unified `rue run` command."""

from __future__ import annotations

import asyncio
from contextlib import closing
from copy import deepcopy
from typing import Annotated
from uuid import UUID

from rich.console import Console
from typer import Option

from rue.cli.options import (
    KeywordOpt,
    SkipTagOpt,
    TagOpt,
    TestPathsArg,
    VerboseOpt,
    resolve_selection,
)
from rue.cli.rendering.errors import print_cli_error, print_definition_errors
from rue.cli.rendering.experiments import experiment_renderer
from rue.cli.rendering.terminal import (
    TerminalExperimentReporter,
    TerminalSuiteReporter,
)
from rue.config import load_config
from rue.context.runtime import SuiteContext
from rue.events import SessionEventsReceiver
from rue.events.processor import SuiteEventsProcessor
from rue.events.receiver import SuiteEventsReceiver
from rue.experiments.executable import ExecutableExperiment
from rue.resources import (
    DependencyResolver,
    registry as default_resource_registry,
)
from rue.storage import TursoSuiteRecorder, TursoSuiteStore
from rue.telemetry.otel import OtelReporter
from rue.testing.discovery import TestDefinitionErrors, TestLoader
from rue.testing.execution.suite.executable import ExecutableSuite


def _resolve_processors(names: list[str]) -> list[SuiteEventsProcessor]:
    """Resolve configured custom processor names into registered instances."""
    resolved = []
    for name in names:
        if name not in SuiteEventsProcessor.REGISTRY:
            available = ", ".join(sorted(SuiteEventsProcessor.REGISTRY))
            raise ValueError(
                f"Unknown processor: {name}. Available: {available}"
            )
        resolved.append(SuiteEventsProcessor.REGISTRY[name])
    return resolved


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
        Option("--timeout", help="Global suite execution timeout in seconds"),
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
    suite_execution_id: Annotated[
        UUID | None,
        Option(
            "--suite-execution-id",
            help="UUID to assign to this suite execution",
        ),
    ] = None,
    processor: Annotated[
        list[str] | None,
        Option(
            "--processor",
            help=(
                "Suite events processor to use "
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
    """Prepare config, suite specs, events, and execution."""
    if experiment:
        match (suite_execution_id, maxfail):
            case (UUID(), _):
                print_cli_error("--suite-execution-id cannot be used with -exp")
                raise SystemExit(2)
            case (_, int()):
                print_cli_error("--maxfail cannot be used with -exp")
                raise SystemExit(2)
            case _:
                pass

    suite_config, collector, resolved_paths = resolve_selection(
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

    suitespec = collector.collect_test_specs(resolved_paths)
    try:
        load_suitespec = deepcopy(suitespec) if experiment else suitespec
        items = TestLoader(load_suitespec.suite_root).load_tests(
            load_suitespec
        )
    except TestDefinitionErrors as errors:
        print_definition_errors(errors)
        raise SystemExit(2) from errors

    if experiment:
        executable_experiment = ExecutableExperiment(config=suite_config)
        experiments = executable_experiment.collect(suitespec)

        session_processors: list[SuiteEventsProcessor] = [
            TerminalExperimentReporter(),
            *_resolve_processors(processor or []),
        ]

        session = SessionEventsReceiver(session_processors)
        session.configure(suite_config)
        with closing(session):
            results = asyncio.run(
                executable_experiment.execute(
                    suitespec,
                    experiments,
                    session=session,
                )
            )
        console = Console()
        for renderable in experiment_renderer.render(
            results,
            suite_config.verbosity,
        ):
            console.print(renderable)
        raise SystemExit(0)

    store = TursoSuiteStore(suite_config.database_path)
    store.initialize()

    if (
        suite_execution_id is not None
        and store.suite_execution_exists(suite_execution_id)
    ):
        print_cli_error(
            f"suite_execution_id '{suite_execution_id}' already exists"
        )
        raise SystemExit(2)

    processors: list[SuiteEventsProcessor] = [TerminalSuiteReporter()]
    if suite_config.otel:
        processors.append(OtelReporter())
    processors.extend(_resolve_processors(suite_config.processors))

    suite_context = (
        SuiteContext(config=suite_config)
        if suite_execution_id is None
        else SuiteContext(
            config=suite_config,
            suite_execution_id=suite_execution_id,
        )
    )
    events_receiver = SuiteEventsReceiver([*processors, TursoSuiteRecorder()])
    with suite_context, events_receiver:
        suite = asyncio.run(
            ExecutableSuite(
                items=items,
                suite_execution_id=suite_context.suite_execution_id,
                resolver=DependencyResolver(default_resource_registry),
            ).execute()
        )
    raise SystemExit(
        0
        if suite.result.failed == 0
        and suite.result.errors == 0
        else 1
    )


__all__ = ["run"]
