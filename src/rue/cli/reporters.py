"""CLI reporter resolution."""

from rue.reports import console as console_reports, otel as otel_reports
from rue.reports.base import Reporter


def resolve_reporters(names: list[str]) -> list[Reporter]:
    """Return configured reporter instances by name."""
    _ = console_reports, otel_reports
    if not names:
        return list(Reporter.REGISTRY.values())

    reporters = []
    for name in names:
        if name not in Reporter.REGISTRY:
            available = ", ".join(sorted(Reporter.REGISTRY))
            msg = f"Unknown reporter: {name}. Available: {available}"
            raise ValueError(msg)
        reporters.append(Reporter.REGISTRY[name])
    return reporters


__all__ = ["resolve_reporters"]
