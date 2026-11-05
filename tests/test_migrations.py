"""Database migrations: website branch, upgrade and current revision."""

import importlib
import textwrap
import uuid

import pytest
from sqlalchemy import inspect

from conftest import BASE_ENV
from evrima import create_app
from evrima.db import db


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A throwaway website package with one model, on a SQLite file.

    Every test gets its own package and table name: Python caches imported
    modules and SQLAlchemy keeps one table registry per process, so reusing a
    name would silently hand the test a previous test's package.
    """
    name = f"migrating_site_{uuid.uuid4().hex[:8]}"
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text(textwrap.dedent(f'''
        """A website with a model of its own."""
        from sqlalchemy.orm import Mapped, mapped_column

        from evrima.db import Base


        class Note(Base):
            __tablename__ = "{name}_notes"
            id: Mapped[int] = mapped_column(primary_key=True)
            text: Mapped[str]
    '''), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.import_module(name)
    database = (tmp_path / "site.sqlite3").as_posix()
    app = create_app(name, environ={**BASE_ENV, "DATABASE_URL": f"sqlite:///{database}"})
    return app, package


def run(app, *args):
    """Invoke `flask evrima db …` and return the result, failing loudly on errors."""
    result = app.test_cli_runner().invoke(args=["evrima", "db", *args])
    assert result.exit_code == 0, result.output + repr(result.exception)
    return result


def tables(app):
    """Names of the tables that exist in the app's database."""
    with app.app_context():
        return set(inspect(db.engine).get_table_names())


def test_upgrade_without_migrations_is_harmless(site):
    app, _ = site
    assert "up to date" in run(app, "upgrade").output


def test_first_website_revision_starts_the_website_branch(site):
    app, package = site
    run(app, "upgrade")
    run(app, "revision", "-m", "create notes")

    [migration] = (package / "migrations" / "versions").glob("*.py")
    source = migration.read_text(encoding="utf-8")
    assert "branch_labels = ('website',)" in source
    assert f"{package.name}_notes" in source

    run(app, "upgrade")
    assert f"{package.name}_notes" in tables(app)
    assert run(app, "current").output.strip()


def test_next_revision_continues_the_branch(site):
    app, package = site
    run(app, "upgrade")
    run(app, "revision", "-m", "create notes")
    run(app, "upgrade")
    run(app, "revision", "-m", "nothing yet", "--empty")

    versions = sorted((package / "migrations" / "versions").glob("*.py"))
    assert len(versions) == 2
    second = next(v for v in versions if "nothing_yet" in v.name).read_text(encoding="utf-8")
    assert "branch_labels = None" in second
    assert "down_revision = None" not in second
