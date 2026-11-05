"""Modules: registration, admin menu, catalogues and migration branches."""

import importlib
import textwrap
import types

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, inspect

from conftest import BASE_ENV
from evrima import create_app
from evrima.config import ConfigError
from evrima.db import db, migrations
from evrima.db.migrations import belongs_to
from evrima.i18n import translate as t
from evrima.modules import Module, enabled_modules
from minimal_site.modules import references


def test_modules_are_enabled_explicitly(make_app):
    assert enabled_modules(make_app()) == {}
    app = make_app(modules=[references])
    assert list(enabled_modules(app)) == ["references"]


def test_a_package_without_a_module_is_refused(make_app):
    with pytest.raises(ConfigError, match="not an Evrima module"):
        make_app(modules=[types.ModuleType("not_a_module")], migrate=False)


def test_a_module_cannot_be_enabled_twice(make_app):
    with pytest.raises(ConfigError, match="enabled twice"):
        make_app(modules=[references, references.module], migrate=False)


def test_the_module_catalogue_is_loaded(make_app):
    app = make_app(modules=[references])
    with app.test_request_context():
        assert t("references.nav") == "Reference"


def test_the_admin_menu_lists_enabled_modules(make_app):
    from conftest import add_admin, https_client, log_in

    plain = make_app()
    add_admin(plain)
    client = https_client(plain)
    log_in(plain, client)
    assert "Obsah" not in client.get("/admin/").get_data(as_text=True)

    app = make_app(modules=[references])
    add_admin(app)
    client = https_client(app)
    log_in(app, client)
    page = client.get("/admin/").get_data(as_text=True)
    assert "Obsah" in page and 'href="/admin/references/"' in page
    page = client.get("/admin/references/new").get_data(as_text=True)
    assert 'href="/admin/references/" class="sidebar__link is-active" aria-current="page"' in page


def test_module_tables_exist_only_where_the_module_is_enabled(make_app):
    with make_app().app_context():
        assert "references_items" not in inspect(db.engine).get_table_names()
    with make_app(modules=[references]).app_context():
        assert "references_items" in inspect(db.engine).get_table_names()


def test_the_references_migration_matches_its_model(make_app):
    app = make_app(modules=[references])
    with app.app_context():
        assert migrations.model_differences("references") == []


def test_model_differences_notice_a_missing_migration(make_app):
    """A column added to a model without a migration shows up."""
    app = make_app(modules=[references])
    extra = Column("extra_note", Integer)
    references.Reference.__table__.append_column(extra)
    try:
        with app.app_context():
            assert migrations.model_differences("references")
    finally:
        references.Reference.__table__._columns.remove(extra)


def test_tables_belong_to_one_branch():
    metadata = MetaData()
    framework = Table("evrima_media_x", metadata, Column("id", Integer, primary_key=True))
    module = Table("evrima_refs_x", metadata, Column("id", Integer, primary_key=True),
                   info={"evrima_module": "refs"})
    website = Table("notes_x", metadata, Column("id", Integer, primary_key=True))
    assert [belongs_to(table, "evrima") for table in (framework, module, website)] == [True, False, False]
    assert [belongs_to(table, "refs") for table in (framework, module, website)] == [False, True, False]
    assert [belongs_to(table, "website") for table in (framework, module, website)] == [False, False, True]


def test_a_website_module_gets_its_own_migration_branch(tmp_path, monkeypatch):
    """A website's own module: `db revision --module` starts its branch in its folder."""
    root = tmp_path / "notes_module"
    root.mkdir()
    notes = Module(name="notes", root=root)
    site = tmp_path / "site_with_notes"
    site.mkdir()
    (site / "__init__.py").write_text('"""A website with its own module."""\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    database = (tmp_path / "site.sqlite3").as_posix()
    app = create_app("site_with_notes", modules=[notes],
                     environ={**BASE_ENV, "DATABASE_URL": f"sqlite:///{database}",
                              "MEDIA_ROOT": str(tmp_path / "media")})
    runner = app.test_cli_runner()

    result = runner.invoke(args=["evrima", "db", "revision", "-m", "start notes", "--module", "notes", "--empty"])
    assert result.exit_code == 0, result.output
    created = list((root / "migrations" / "versions").glob("*.py"))
    assert len(created) == 1
    assert "branch_labels = ('notes',)" in created[0].read_text(encoding="utf-8")

    result = runner.invoke(args=["evrima", "db", "revision", "-m", "x", "--module", "missing", "--empty"])
    assert result.exit_code != 0
    assert "not enabled" in result.output


def test_website_migrations_leave_module_tables_alone(tmp_path, monkeypatch):
    """Comparing models for a website migration ignores framework and module tables.

    The references model is imported (other tests use it) but the module is
    not enabled: a website migration must not create its table.
    """
    site = tmp_path / "site_without_references"
    site.mkdir()
    (site / "__init__.py").write_text(textwrap.dedent('''
        """A website with one model of its own."""
        from sqlalchemy.orm import Mapped, mapped_column

        from evrima.db import Base


        class Memo(Base):
            __tablename__ = "site_without_references_memos"
            id: Mapped[int] = mapped_column(primary_key=True)
    '''), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.import_module("site_without_references")
    database = (tmp_path / "site.sqlite3").as_posix()
    app = create_app("site_without_references",
                     environ={**BASE_ENV, "DATABASE_URL": f"sqlite:///{database}",
                              "MEDIA_ROOT": str(tmp_path / "media")})
    runner = app.test_cli_runner()
    assert runner.invoke(args=["evrima", "db", "upgrade"]).exit_code == 0
    result = runner.invoke(args=["evrima", "db", "revision", "-m", "memos"])
    assert result.exit_code == 0, result.output

    migration = next((site / "migrations" / "versions").glob("*.py")).read_text(encoding="utf-8")
    assert "site_without_references_memos" in migration
    assert "references_items" not in migration


def test_website_migrations_keep_tables_of_enabled_modules(tmp_path, monkeypatch):
    """A module table already in the database is not taken for the website's.

    Website modules name their tables freely (not with evrima_), and the
    database does not remember which module a table belongs to. The enabled
    module's model is known, so the website migration neither creates nor
    drops its table.
    """
    site = tmp_path / "site_with_references"
    site.mkdir()
    (site / "__init__.py").write_text('"""A website with the references module."""\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    database = (tmp_path / "site.sqlite3").as_posix()
    app = create_app("site_with_references", modules=[references],
                     environ={**BASE_ENV, "DATABASE_URL": f"sqlite:///{database}",
                              "MEDIA_ROOT": str(tmp_path / "media")})
    runner = app.test_cli_runner()
    assert runner.invoke(args=["evrima", "db", "upgrade"]).exit_code == 0
    result = runner.invoke(args=["evrima", "db", "revision", "-m", "nothing"])
    assert result.exit_code == 0, result.output

    migration = next((site / "migrations" / "versions").glob("*.py")).read_text(encoding="utf-8")
    assert "references_items" not in migration


@pytest.mark.parametrize("name", ["website", "evrima", "Pricing", "price-list", "2nd", ""])
def test_module_names_are_checked(make_app, tmp_path, name):
    """The name doubles as a migration branch label, so it must not clash or be odd."""
    with pytest.raises(ConfigError, match="not allowed"):
        make_app(modules=[Module(name=name, root=tmp_path)], migrate=False)


def test_an_unprotected_admin_blueprint_is_refused(make_app, tmp_path):
    """Forgetting protect() would publish the module's admin to everyone."""
    from flask import Blueprint

    bp = Blueprint("pricing_admin", __name__, url_prefix="/admin/pricing")
    with pytest.raises(ConfigError, match="without login"):
        make_app(modules=[Module(name="pricing", root=tmp_path, blueprints=(bp,))], migrate=False)


def _site_app(tmp_path, modules):
    """An app over one file database, so it can be rebuilt with other modules."""
    database = (tmp_path / "site.sqlite3").as_posix()
    return create_app("fixture_site", modules=modules,
                      environ={**BASE_ENV, "DATABASE_URL": f"sqlite:///{database}",
                               "MEDIA_ROOT": str(tmp_path / "media")})


def test_a_module_dropped_without_removal_gets_a_clear_error(tmp_path):
    with_module = _site_app(tmp_path, [references])
    assert with_module.test_cli_runner().invoke(args=["evrima", "db", "upgrade"]).exit_code == 0

    result = _site_app(tmp_path, []).test_cli_runner().invoke(args=["evrima", "db", "upgrade"])
    assert result.exit_code != 0
    assert "remove-module" in result.output


def test_remove_module_drops_its_tables(tmp_path):
    with_module = _site_app(tmp_path, [references])
    runner = with_module.test_cli_runner()
    assert runner.invoke(args=["evrima", "db", "upgrade"]).exit_code == 0
    result = runner.invoke(args=["evrima", "db", "remove-module", "references", "--yes"])
    assert result.exit_code == 0, result.output

    without = _site_app(tmp_path, [])
    assert without.test_cli_runner().invoke(args=["evrima", "db", "upgrade"]).exit_code == 0
    with without.app_context():
        tables = inspect(db.engine).get_table_names()
    assert "references_items" not in tables and "evrima_media" in tables


def test_website_migrations_never_drop_tables_without_a_model(tmp_path, monkeypatch):
    """A leftover table (e.g. of a removed module) is never dropped by a generated migration."""
    site = tmp_path / "site_with_leftover"
    site.mkdir()
    (site / "__init__.py").write_text('"""A website with a leftover table."""\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    database = (tmp_path / "site.sqlite3").as_posix()
    app = create_app("site_with_leftover",
                     environ={**BASE_ENV, "DATABASE_URL": f"sqlite:///{database}",
                              "MEDIA_ROOT": str(tmp_path / "media")})
    runner = app.test_cli_runner()
    assert runner.invoke(args=["evrima", "db", "upgrade"]).exit_code == 0
    with app.app_context():
        Table("leftover_things", MetaData(), Column("id", Integer, primary_key=True)).create(db.engine)
    result = runner.invoke(args=["evrima", "db", "revision", "-m", "nothing"])
    assert result.exit_code == 0, result.output
    migration = next((site / "migrations" / "versions").glob("*.py")).read_text(encoding="utf-8")
    assert "leftover_things" not in migration
