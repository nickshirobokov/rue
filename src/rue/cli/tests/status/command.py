"""`rue tests status` command."""

from __future__ import annotations

from rich.console import Console

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
from rue.cli.tests.status.builder import TestsStatusBuilder
from rue.cli.tests.status.render import StatusRenderer
from rue.config import load_config
from rue.storage.sqlite import SQLiteStore
from rue.testing.discovery import TestDefinitionErrors


status_renderer = StatusRenderer()


def status(
    paths: TestPathsArg = None,
    keyword: KeywordOpt = None,
    tag: TagOpt = None,
    skip_tag: SkipTagOpt = None,
    verbose: VerboseOpt = 0,
    db_path: DBPathOpt = None,
) -> None:
    """Show collected tests and their pre-run status."""
    status_config, collector, resolved_paths = resolve_selection(
        config=load_config(),
        paths=paths,
        keyword=keyword,
        tag=tag,
        skip_tag=skip_tag,
        verbose=verbose,
        db_path=db_path,
    )
    collection = collector.build_spec_collection(resolved_paths)
    builder = TestsStatusBuilder(status_config)
    store = None
    if status_config.resolved_db_path.exists():
        store = SQLiteStore(status_config.resolved_db_path)
    try:
        report = builder.build(collection, store=store)
    except TestDefinitionErrors as errors:
        print_definition_errors(errors)
        raise SystemExit(2) from errors
    Console().print(status_renderer.render(report, status_config.verbosity))


__all__ = ["status", "status_renderer"]
