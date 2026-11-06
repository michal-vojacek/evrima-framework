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


@evrima_cli.group("telemetry")
def telemetry_cli() -> None:
    """Telemetry (see the protocol in the evrima-telemetry repository)."""


@telemetry_cli.command("ship")
def telemetry_ship_command() -> None:
    """Send buffered telemetry to the collector. Run every minute; does nothing when telemetry is off."""
    from evrima.telemetry import ship

    try:
        sent = ship.ship()
    except ship.ShipError as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Sent {sent} telemetry event(s).")


@evrima_cli.command("jobs")
@click.option("--ship-every", default=60, show_default=True, help="Seconds between telemetry shipments.")
@click.option("--cleanup-every", default=24 * 3600, show_default=True, help="Seconds between daily cleanups (unused uploads, old login records).")
def jobs_command(ship_every: int, cleanup_every: int) -> None:
    """Run the periodic jobs until stopped: ship telemetry, clean up uploads and login records.

    Meant for a sidecar container of the website (docker-compose.yml): the
    deploy platform has no cron. A failing job is logged and retried at its
    next turn; it never stops the loop.

    Each job runs in its own app context, so its database session is closed
    after it (code review 2026-11-06): one session for the whole loop kept a
    transaction open for a day, which blocked migrations of the tables it had
    read, and after a database restart it stayed broken until the container
    was restarted. SIGTERM (`docker stop`) ends the loop between jobs, so a
    batch is never cut off after the collector took it.
    """
    import signal
    import threading
    import time

    from flask import current_app

    from evrima import media
    from evrima.auth import cleanup as auth_cleanup
    from evrima.telemetry import ship

    app = current_app._get_current_object()
    stop = threading.Event()

    def request_stop(signum, frame):
        click.echo("Stopping after the current job.")
        stop.set()
    for name in ("SIGTERM", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), request_stop)

    def run(label: str, job) -> None:
        try:
            with app.app_context():
                result = job()
            if result:
                click.echo(f"{label}: {result}.")
        except Exception as error:  # noqa: BLE001 - the loop must survive anything
            click.echo(f"{label} failed: {type(error).__name__}: {error}", err=True)

    next_ship = next_cleanup = time.monotonic()
    click.echo(f"Evrima {get_version()}: jobs running (telemetry every {ship_every} s, "
               f"cleanup every {cleanup_every} s).")
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_ship:
            next_ship = now + ship_every
            run("Telemetry events sent", ship.ship)
        if not stop.is_set() and now >= next_cleanup:
            next_cleanup = now + cleanup_every
            run("Unused files removed", media.cleanup)
            run("Old login records removed", auth_cleanup.cleanup)
        stop.wait(max(1.0, min(next_ship, next_cleanup) - time.monotonic()))
    click.echo("Jobs stopped.")


for _command in ACCOUNT_COMMANDS:
    evrima_cli.add_command(_command)


def register(app: Flask) -> None:
    """Add the `evrima` command group to `app`."""
    app.cli.add_command(evrima_cli)
