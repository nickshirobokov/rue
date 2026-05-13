"""CLI module for Rue."""

from __future__ import annotations

import sys

from typer import Typer

from rue.cli import init as init_module, run as run_module
from rue.cli.db import db_app
from rue.cli.status.command import status as status_cmd
from rue.config import load_config


app = Typer(
    name="rue",
    help="Rue AI Testing Framework",
    no_args_is_help=True,
)
app.add_typer(db_app, name="db")
app.command()(init_module.init)
app.command()(run_module.run)
app.command()(status_cmd)


def main() -> None:
    """Entry point for the rue CLI."""
    config = load_config()
    argv = [*config.addopts, *sys.argv[1:]] if config.addopts else sys.argv[1:]
    app(argv)


__all__ = ["app", "main"]
