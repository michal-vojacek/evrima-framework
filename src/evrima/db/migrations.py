"""Database migrations (Alembic) for the framework, its modules and the website.

Each part keeps its own migration branch in its own folder:

- the framework: `evrima/migrations/versions/`, branch label `evrima`,
- the website: `<website package>/migrations/versions/`, branch label `website`,
- modules can add their folders with `add_migrations` (branch label = module name).

When a migration is created by comparing models with the database, it only
looks at its own branch's tables (`belongs_to`): framework tables start with
`evrima_`, module tables carry `info={"evrima_module": name}`, everything
else is the website's. So a website migration never creates, changes or
drops a table of the framework or of a module, enabled or not.

All branches share one `alembic_version` table, so `flask evrima db upgrade`
brings every part up to date in one step, before the new version starts
(docs/framework.md, "Distribution and deployment"). A website migration that
needs a framework table names it with Alembic's `depends_on`.

Migration rules (docs/framework.md, "Versioning rules"): in PATCH and MINOR
releases migrations only add; new columns are nullable or have a database
default, so the previous code keeps working with the new schema.
"""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from flask import Flask, current_app

FRAMEWORK_BRANCH = "evrima"
WEBSITE_BRANCH = "website"
SCRIPT_LOCATION = Path(__file__).resolve().parent.parent / "migrations"
FRAMEWORK_VERSIONS = SCRIPT_LOCATION / "versions"

_EXTENSION_KEY = "evrima.migrations"


def init_app(app: Flask) -> None:
    """Record the migration folders of the framework and of the website."""
    app.extensions[_EXTENSION_KEY] = [FRAMEWORK_VERSIONS]
    website = website_versions(app)
    if website.is_dir():
        app.extensions[_EXTENSION_KEY].append(website)


def add_migrations(app: Flask, directory: Path | str) -> None:
    """Add a module's migration folder to `app`."""
    app.extensions[_EXTENSION_KEY].append(Path(directory))


def website_versions(app: Flask) -> Path:
    """The folder that holds (or will hold) the website's migrations."""
    return Path(app.root_path) / "migrations" / "versions"


def alembic_config(branch: str | None = None) -> Config:
    """Build the Alembic configuration for the current app, without an .ini file.

    `branch` is the branch a new migration is created on; env.py reads it to
    compare only that branch's tables.
    """
    config = Config()
    config.attributes["evrima_branch"] = branch
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    # "os" separates folders with os.pathsep (";" on Windows), which never
    # occurs inside a path, unlike a space.
    config.set_main_option("path_separator", "os")
    folders = [str(folder) for folder in current_app.extensions[_EXTENSION_KEY]]
    config.set_main_option("version_locations", os.pathsep.join(folders))
    return config


def upgrade() -> None:
    """Apply every pending migration of every branch."""
    _explain_unknown_revisions(lambda: command.upgrade(alembic_config(), "heads"))


def current() -> list[str]:
    """Return the revisions the database is at, one per branch."""
    from alembic.runtime.migration import MigrationContext
    from evrima.db import db

    with db.engine.connect() as connection:
        return sorted(MigrationContext.configure(connection).get_current_heads())


class UnknownRevision(Exception):
    """The database is at a revision none of the enabled parts knows."""


def _explain_unknown_revisions(action):
    """Run `action`, turning Alembic's "Can't locate revision" into a clear message."""
    from alembic.util import CommandError

    try:
        return action()
    except CommandError as error:
        if "Can't locate revision" not in str(error):
            raise
        raise UnknownRevision(
            f"{error}. The database holds migrations of a module that is not enabled. "
            "Enable the module again; to remove a module for good, run "
            "`flask evrima db remove-module <name>` while it is still enabled (docs/modules.md).") from error


def remove_module(name: str) -> None:
    """Drop the tables of an enabled module by running its migrations down to the start.

    The module must still be enabled, so that Alembic finds its migrations.
    Afterwards the website stops enabling it and its code can be deleted.
    """
    from evrima.modules import enabled_modules

    if name not in enabled_modules(current_app):
        raise ValueError(f"Module {name!r} is not enabled in this app.")
    _explain_unknown_revisions(lambda: command.downgrade(alembic_config(), f"{name}@base"))


def has_branch(label: str) -> bool:
    """True when some revision already carries the branch label `label`."""
    script = ScriptDirectory.from_config(alembic_config())
    return any(label in (revision.branch_labels or ()) for revision in script.walk_revisions())


def belongs_to(table, branch: str) -> bool:
    """True when `table` (a SQLAlchemy Table, possibly reflected) is part of `branch`."""
    module = table.info.get("evrima_module")
    if branch == FRAMEWORK_BRANCH:
        return module is None and table.name.startswith("evrima_")
    if branch == WEBSITE_BRANCH:
        return module is None and not table.name.startswith("evrima_")
    return module == branch


def create_revision(message: str, *, framework: bool = False, module: str | None = None,
                    autogenerate: bool = True):
    """Create a new migration on the website branch, or the framework's or a module's.

    The first revision of a branch starts it: it gets the branch label and its
    own folder. Later revisions continue from the branch head.
    """
    if module is not None:
        from evrima.modules import enabled_modules

        enabled = enabled_modules(current_app)
        if module not in enabled:
            raise ValueError(f"Module {module!r} is not enabled in this app.")
        label, folder = module, enabled[module].root / "migrations" / "versions"
    elif framework:
        label, folder = FRAMEWORK_BRANCH, FRAMEWORK_VERSIONS
    else:
        label, folder = WEBSITE_BRANCH, website_versions(current_app)
    config = alembic_config(label)
    if has_branch(label):
        return command.revision(
            config, message=message, autogenerate=autogenerate, head=f"{label}@head")
    folder.mkdir(parents=True, exist_ok=True)
    # The new folder must be a version location before Alembic can write to it.
    if folder not in current_app.extensions[_EXTENSION_KEY]:
        current_app.extensions[_EXTENSION_KEY].append(folder)
        config = alembic_config(label)
    return command.revision(
        config, message=message, autogenerate=autogenerate, head="base",
        branch_label=label, version_path=str(folder))


def model_differences(branch: str) -> list:
    """Differences between the models of `branch` and the migrated database.

    An empty list means the migrations create exactly what the models
    describe. Every module tests this after `upgrade()`; a non-empty result
    usually means a model changed without a new migration.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from evrima.db import Base, db

    def include(obj, name, type_, reflected, compare_to):
        table = obj if type_ == "table" else getattr(obj, "table", None)
        if table is None:
            return True
        model = Base.metadata.tables.get(table.name)
        return belongs_to(model if model is not None else table, branch)

    with db.engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "include_object": include})
        return compare_metadata(context, Base.metadata)
