"""`rue experiments run` command."""

from __future__ import annotations

from typing import Annotated

from rich.console import Console
from typer import Option

from rue.cli.errors import print_definition_errors
from rue.cli.experiments.render import experiment_renderer
from rue.cli.tests.options import (
    KeywordOpt,
    SkipTagOpt,
    TagOpt,
    TestPathsArg,
    VerboseOpt,
    resolve_selection,
)
from rue.config import load_config
from rue.experiments.runner import ExperimentRunner
from rue.testing.discovery import TestDefinitionErrors, TestLoader


def run(
    paths: TestPathsArg = None,
    keyword: KeywordOpt = None,
    tag: TagOpt = None,
    skip_tag: SkipTagOpt = None,
    concurrency: Annotated[
        int | None,
        Option(
            "--concurrency",
            help="Number of concurrent tests inside each variant",
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        Option("--timeout", help="Global timeout per variant in seconds"),
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
) -> None:
    """Run experiment variants."""
    runner_config, collector, resolved_paths = resolve_selection(
        config=load_config(),
        paths=paths,
        keyword=keyword,
        tag=tag,
        skip_tag=skip_tag,
        verbose=verbose,
        quiet=quiet,
        concurrency=max(0, concurrency) if concurrency is not None else None,
        timeout=timeout if timeout and timeout > 0 else None,
        otel=otel,
        processors=[],
    )
    runner_config = runner_config.model_copy(
        update={
            "maxfail": None,
            "processors": [],
        }
    )
    collection = collector.build_spec_collection(resolved_paths)
    try:
        TestLoader(collection.suite_root).load_from_collection(collection)
        collection = collector.build_spec_collection(resolved_paths)
        experiment_runner = ExperimentRunner(config=runner_config)
        experiments = experiment_runner.collect(collection)
        if not experiments:
            Console().print("[yellow]No experiments found.[/yellow]")
            raise SystemExit(0)

        results = experiment_runner.run(collection, experiments)
    except TestDefinitionErrors as errors:
        print_definition_errors(errors)
        raise SystemExit(2) from errors
    console = Console()
    for renderable in experiment_renderer.render(
        results,
        runner_config.verbosity,
    ):
        console.print(renderable)
    raise SystemExit(0)


__all__ = ["ExperimentRunner", "load_config", "run"]
