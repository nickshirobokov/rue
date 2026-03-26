"""Reporting module for rue test output."""

from rue.reports.base import Reporter
from rue.reports.console import ConsoleReporter
from rue.reports.otel import OtelReporter
from rue.reports.registry import (
    _builtin_registry,
    _reporter_registry,
    get_reporter_registry,
    reporter,
    resolve_reporter,
    resolve_reporters,
)


_reporter_registry["ConsoleReporter"] = ConsoleReporter
_builtin_registry["ConsoleReporter"] = ConsoleReporter
_reporter_registry["OtelReporter"] = OtelReporter
_builtin_registry["OtelReporter"] = OtelReporter

__all__ = [
    "ConsoleReporter",
    "OtelReporter",
    "Reporter",
    "get_reporter_registry",
    "reporter",
    "resolve_reporter",
    "resolve_reporters",
]
