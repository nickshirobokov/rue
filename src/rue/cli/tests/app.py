"""Typer app wiring for `rue tests`."""

from click.core import Context
from typer import Typer
from typer.core import TyperGroup

from rue.cli.tests.run import run
from rue.cli.tests.status import status


class DefaultCommandGroup(TyperGroup):
    """Route bare group invocations to the default subcommand."""

    default_command_name = "run"

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        if ctx.resilient_parsing:
            return super().parse_args(ctx, args)
        if args and args[0] in {"--help", "-h"}:
            return super().parse_args(ctx, args)
        if args and args[0] in self.commands:
            return super().parse_args(ctx, args)
        return super().parse_args(ctx, [self.default_command_name, *args])


tests_app = Typer(cls=DefaultCommandGroup, help="Test operations")
tests_app.command()(run)
tests_app.command()(status)


__all__ = ["DefaultCommandGroup", "tests_app"]
