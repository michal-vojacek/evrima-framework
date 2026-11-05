"""Alembic environment: runs migrations against the database of the current app.

Alembic is started from `flask evrima db …` (evrima/db/migrations.py), so a
Flask app context exists and the engine and models come from the app instead
of an alembic.ini file.
"""

from alembic import context
from flask import current_app

from evrima.db import Base, db
from evrima.db.migrations import belongs_to

target_metadata = Base.metadata
# Set when a new migration is created; None while migrations only run.
BRANCH = context.config.attributes.get("evrima_branch")


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Compare only the tables of the branch the new migration belongs to."""
    if BRANCH is None:
        return True
    if type_ == "table" and reflected and compare_to is None:
        # A table in the database without a model: its module may just be
        # disabled or its code removed, and the database does not remember
        # whose table it is. Dropping data is never generated; write such a
        # migration by hand, or remove a module with `db remove-module`.
        return False
    table = obj if type_ == "table" else getattr(obj, "table", None)
    return table is None or belongs_to(table, BRANCH)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic --sql)."""
    context.configure(
        url=current_app.config["DATABASE_URL"],
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations over a connection of the app's engine."""
    with db.engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            # SQLite cannot alter tables in place; batch mode recreates them.
            # Only development and tests use SQLite (production is PostgreSQL).
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
