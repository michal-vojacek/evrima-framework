"""Command-line administration of admin accounts.

`create-admin` makes the first administrator of a new website. E-mail changes
happen here only, so a client cannot redirect an account to another mailbox
from the admin (docs/framework.md, "Admin login").
"""

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from evrima.auth import audit, credentials, sessions
from evrima.auth.models import Administrator
from evrima.auth.views import EMAIL_PATTERN, normalise_email
from evrima.db import db, utcnow
from evrima.i18n import LANGUAGES


def _ask_password() -> str:
    """Prompt for a password twice, hidden, until it meets the rules."""
    while True:
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        if credentials.password_problem(password) is None:
            return password
        click.echo(f"The password needs at least {credentials.PASSWORD_MIN_LENGTH} characters.")


def _find(email: str) -> Administrator:
    """The administrator with `email`, or a clean error for the command line."""
    admin = db.session.scalar(select(Administrator).where(Administrator.email == normalise_email(email)))
    if admin is None:
        raise click.ClickException(f"No administrator with the e-mail {email}.")
    return admin


@click.command("create-admin")
@with_appcontext
@click.argument("email")
@click.option("--name", default="", help="Name shown in the admin.")
@click.option("--language", type=click.Choice(sorted(LANGUAGES)), default="cs", show_default=True)
def create_admin_command(email: str, name: str, language: str) -> None:
    """Create an administrator who can log in straight away."""
    email = normalise_email(email)
    if not EMAIL_PATTERN.match(email):
        raise click.ClickException("That is not a valid e-mail address.")
    if db.session.scalar(select(Administrator).where(Administrator.email == email)):
        raise click.ClickException("An administrator with this e-mail already exists.")
    admin = Administrator(
        email=email, name=name.strip(), language=language,
        password_hash=credentials.hash_password(_ask_password()), password_changed_at=utcnow())
    db.session.add(admin)
    db.session.commit()
    audit.record("admin.created_cli", admin=admin)
    click.echo(f"Administrator {email} created.")


@click.command("set-admin-email")
@with_appcontext
@click.argument("current_email")
@click.argument("new_email")
def set_admin_email_command(current_email: str, new_email: str) -> None:
    """Change an administrator's e-mail; their sessions end."""
    admin = _find(current_email)
    new_email = normalise_email(new_email)
    if not EMAIL_PATTERN.match(new_email):
        raise click.ClickException("That is not a valid e-mail address.")
    if db.session.scalar(select(Administrator).where(Administrator.email == new_email)):
        raise click.ClickException("Another administrator already uses that e-mail.")
    old = admin.email
    admin.email = new_email
    db.session.commit()
    sessions.end_all(admin)
    audit.record("admin.email_changed", admin=admin, detail=f"{old} -> {new_email}")
    click.echo(f"E-mail changed to {new_email}.")


@click.command("set-admin-password")
@with_appcontext
@click.argument("email")
def set_admin_password_command(email: str) -> None:
    """Set a new password for an administrator (e.g. when the mailbox is unavailable)."""
    admin = _find(email)
    admin.password_hash = credentials.hash_password(_ask_password())
    admin.password_changed_at = utcnow()
    db.session.commit()
    sessions.end_all(admin)
    audit.record("password.set_cli", admin=admin)
    click.echo("Password changed; the administrator's sessions have ended.")


COMMANDS = (create_admin_command, set_admin_email_command, set_admin_password_command)
