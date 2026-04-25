"""Typer app wiring for `rue experiments`."""

from typer import Typer

from rue.cli.experiments.run import run


experiments_app = Typer(help="Experiment operations")
experiments_app.command()(run)


__all__ = ["experiments_app"]
