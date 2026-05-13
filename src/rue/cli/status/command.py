"""`rue status` command."""

from __future__ import annotations

from rich.console import Console

from rue.cli.options import (
    DatabasePathOpt,
    KeywordOpt,
    SkipTagOpt,
    TagOpt,
    TestPathsArg,
    VerboseOpt,
    resolve_selection,
)
from rue.cli.rendering.errors import print_definition_errors
from rue.cli.rendering.tests import TestTreeRenderer
from rue.cli.status.builder import TestsStatusBuilder
from rue.config import load_config
from rue.testing.discovery import TestDefinitionErrors


def status(
    paths: TestPathsArg = None,
    keyword: KeywordOpt = None,
    tag: TagOpt = None,
    skip_tag: SkipTagOpt = None,
    verbose: VerboseOpt = 0,
    database_path: DatabasePathOpt = None,
) -> None:
    """Show collected tests and their pre-run status."""
    status_config, collector, resolved_paths = resolve_selection(
        config=load_config(),
        paths=paths,
        keyword=keyword,
        tag=tag,
        skip_tag=skip_tag,
        verbose=verbose,
        database_path=database_path,
    )
    suitespec = collector.collect_test_specs(resolved_paths)
    builder = TestsStatusBuilder(status_config)
    try:
        report = builder.build(suitespec)
    except TestDefinitionErrors as errors:
        print_definition_errors(errors)
        raise SystemExit(2) from errors
    Console().print(TestTreeRenderer().render(report, status_config.verbosity))


__all__ = ["status"]
