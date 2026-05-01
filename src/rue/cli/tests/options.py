"""Shared options and selection resolution for test CLI commands."""

from typing import Annotated, Any

from typer import Argument, Option

from rue.config import Config
from rue.testing.discovery import TestSpecCollector


TestPathsArg = Annotated[
    list[str] | None,
    Argument(help="Test files or directories"),
]
KeywordOpt = Annotated[
    str | None,
    Option("-k", "--keyword", help="Filter tests by keyword expression"),
]
TagOpt = Annotated[
    list[str] | None,
    Option("-t", "--tag", help="Run tests with given tag"),
]
SkipTagOpt = Annotated[
    list[str] | None,
    Option("--skip-tag", help="Skip tests that match this tag"),
]
VerboseOpt = Annotated[
    int,
    Option("-v", "--verbose", count=True, help="Increase CLI output"),
]
DBPathOpt = Annotated[
    str | None,
    Option("--db-path", help="Path to the Rue SQLite database"),
]


def resolve_selection(
    *,
    config: Config,
    paths: list[str] | None,
    keyword: str | None,
    tag: list[str] | None,
    skip_tag: list[str] | None,
    verbose: int,
    quiet: int = 0,
    db_path: str | None = None,
    **overrides: Any,
) -> tuple[Config, TestSpecCollector, list[str]]:
    include_tags = [*config.include_tags, *(tag or [])]
    exclude_tags = [*config.exclude_tags, *(skip_tag or [])]
    resolved_paths = paths or config.test_paths
    resolved_config = config.with_overrides(
        keyword=keyword,
        db_path=db_path,
        verbosity=config.verbosity + verbose - quiet,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        **overrides,
    )
    collector = TestSpecCollector(
        include_tags,
        exclude_tags,
        keyword or resolved_config.keyword,
    )
    return resolved_config, collector, resolved_paths


__all__ = [
    "DBPathOpt",
    "KeywordOpt",
    "SkipTagOpt",
    "TagOpt",
    "TestPathsArg",
    "TestSpecCollector",
    "VerboseOpt",
    "resolve_selection",
]
