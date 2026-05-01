"""Console processor package for rue test output using Rich."""

from rue.cli.console.reporter import ConsoleReporter
from rue.storage import rich_traceback_from_json as rich_traceback_from_json


console_reporter = ConsoleReporter()

__all__ = ["ConsoleReporter", "console_reporter", "rich_traceback_from_json"]
