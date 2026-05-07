"""CLI error rendering."""

from rich.console import Console

from rue.testing.discovery import TestDefinitionErrors


def print_cli_error(message: str) -> None:
    """Print a single CLI validation error."""
    Console().print(f"[red]{message}[/red]")


def print_definition_errors(errors: TestDefinitionErrors) -> None:
    """Print selected-test definition errors."""
    console = Console()
    console.print("[red]Test definition errors[/red]")
    for issue in errors.exceptions:
        console.print(f"[red]- {issue}[/red]")


__all__ = ["print_cli_error", "print_definition_errors"]
