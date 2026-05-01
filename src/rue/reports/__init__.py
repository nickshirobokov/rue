"""Reporting module for rue test output."""

from rue.reports.console import ConsoleReporter
from rue.reports.otel import OtelReporter


__all__ = [
    "ConsoleReporter",
    "OtelReporter",
]
