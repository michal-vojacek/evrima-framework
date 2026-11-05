"""Command-line commands, available as `flask evrima <command>`."""

import click
from flask import Flask, current_app
from flask.cli import AppGroup

from evrima.auth.cli import COMMANDS as ACCOUNT_COMMANDS
from evrima.config import describe_config
from evrima.db import migrations
from evrima.version import get_version

evrima_cli = AppGroup("evrima", help="Evrima framework commands.")


@evrima_cli.command("version")
def version_command() -> None:
    """Print the installed Evrima version."""
    click.echo(get_version())


@evrima_cli.command("check-config")
def check_config_command() -> None:
    """Print a summary of the configuration, without secrets.

    Reaching this command already means the configuration passed validation:
    the app factory refuses to build an app with an invalid one.
    """
    click.echo(f"Evrima {get_version()}: configuration is valid.")
    for key, value in describe_config(current_app.config).items():
        click.echo(f"  {key}: {value}")


@evrima_cli.group("db")
def db_cli() -> None:
    """Database migrations of the framework, modules and the website."""


@db_cli.command("upgrade")
def db_upgrade_command() -> None:
    """Apply every pending migration. Deploys run this before the new version starts."""
    try:
        migrations.upgrade()
    except migrations.UnknownRevision as error:
        raise click.ClickException(str(error)) from error
    click.echo("Database is up to date: " + (", ".join(migrations.current()) or "no migrations"))


@db_cli.command("current")
def db_current_command() -> None:
    """Print the revision of every branch the database is at."""
    click.echo("\n".join(migrations.current()) or "No migrations applied.")


@db_cli.command("remove-module")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def db_remove_module_command(name: str, yes: bool) -> None:
    """Delete an enabled module's tables and data, so it can be removed from the website."""
    if not yes:
        click.confirm(f"Delete every table and all data of module {name!r}?", abort=True)
    try:
        migrations.remove_module(name)
    except (ValueError, migrations.UnknownRevision) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Module {name!r} removed from the database. Stop enabling it in create_app().")


@db_cli.command("revision")
@click.option("-m", "--message", required=True, help="What the migration does.")
@click.option("--framework", is_flag=True, help="Create it on the framework branch (Evrima development).")
@click.option("--module", help="Create it on the branch of this enabled module.")
@click.option("--empty", is_flag=True, help="Do not compare models with the database.")
def db_revision_command(message: str, framework: bool, module: str | None, empty: bool) -> None:
    """Create a migration on the website branch, comparing models with the database."""
    try:
        migrations.create_revision(message, framework=framework, module=module, autogenerate=not empty)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


@evrima_cli.group("media")
def media_cli() -> None:
    """Uploaded files."""


@media_cli.command("cleanup")
def media_cleanup_command() -> None:
    """Delete files uploaded more than 24 hours ago and never used by a saved form. Run daily."""
    from evrima import media

    click.echo(f"Removed {media.cleanup()} unused file(s).")


for _command in ACCOUNT_COMMANDS:
    evrima_cli.add_command(_command)


def register(app: Flask) -> None:
    """Add the `evrima` command group to `app`."""
    app.cli.add_command(evrima_cli)
