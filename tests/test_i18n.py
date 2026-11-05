"""Admin text catalogues, plural forms and the current language."""

import os

import pytest

from evrima import i18n
from evrima.i18n import Catalogue, CatalogueError, FRAMEWORK_CATALOGUE


def write(path, text):
    """Write a catalogue file and return its path."""
    path.write_text(text, encoding="utf-8")
    return path


def test_nested_tables_become_dotted_keys(tmp_path):
    catalogue = Catalogue()
    catalogue.load_file(write(tmp_path / "a.toml", '[demo.save]\nen = "Save"\ncs = "Uložit"\n'))
    assert catalogue.text("demo.save", "cs") == "Uložit"
    assert catalogue.text("demo.save", "en") == "Save"


def test_missing_language_falls_back_to_english(tmp_path):
    catalogue = Catalogue()
    catalogue.load_file(write(tmp_path / "a.toml", '[demo.only_en]\nen = "Only English"\n'))
    assert catalogue.text("demo.only_en", "cs") == "Only English"
    assert catalogue.missing() == ["demo.only_en: cs"]


def test_czech_plural_forms(tmp_path):
    catalogue = Catalogue()
    catalogue.load_file(write(tmp_path / "a.toml", (
        '[demo.photos]\n'
        'en = { one = "{count} photo", other = "{count} photos" }\n'
        'cs = { one = "{count} fotka", few = "{count} fotky", other = "{count} fotek" }\n')))
    forms = {n: catalogue.text("demo.photos", "cs", n) for n in (0, 1, 2, 4, 5, 22)}
    assert forms == {0: "{count} fotek", 1: "{count} fotka", 2: "{count} fotky",
                     4: "{count} fotky", 5: "{count} fotek", 22: "{count} fotek"}
    assert catalogue.text("demo.photos", "en", 1) == "{count} photo"
    assert catalogue.text("demo.photos", "en", 2) == "{count} photos"


def test_duplicate_key_across_files_is_an_error(tmp_path):
    catalogue = Catalogue()
    catalogue.load_file(write(tmp_path / "a.toml", '[demo.x]\nen = "A"\ncs = "A"\n'))
    with pytest.raises(CatalogueError, match="defined in both"):
        catalogue.load_file(write(tmp_path / "b.toml", '[demo.x]\nen = "B"\ncs = "B"\n'))


def test_unknown_language_is_an_error(tmp_path):
    with pytest.raises(CatalogueError, match="unknown languages"):
        Catalogue().load_file(write(tmp_path / "a.toml", '[demo.x]\nen = "A"\nde = "B"\n'))


def test_every_framework_text_exists_in_every_language():
    catalogue = Catalogue()
    catalogue.load_directory(FRAMEWORK_CATALOGUE)
    assert catalogue.messages, "the framework catalogue should not be empty"
    assert catalogue.missing() == []


def test_translate_uses_session_language_and_fills_placeholders(app):
    with app.test_request_context():
        assert i18n.get_language() == "cs"
        assert i18n.translate("admin.common.save") == "Uložit"
    with app.test_request_context():
        i18n.set_language("en")
        assert i18n.translate("admin.js.tags.remove", name="wood") == "Remove wood"
        assert i18n.translate_plural("admin.design.languages.photos", 3) == "3 photos"


def test_unknown_key_renders_as_the_key(app):
    with app.test_request_context():
        assert i18n.translate("admin.no.such.key") == "admin.no.such.key"


def test_wrong_placeholder_does_not_break_rendering(app):
    with app.test_request_context():
        assert i18n.translate("admin.js.tags.remove", other="x") == "Odebrat {name}"


def test_unsupported_language_is_rejected(app):
    with app.test_request_context(), pytest.raises(ValueError):
        i18n.set_language("de")


def test_default_language_comes_from_config(make_app):
    app = make_app(env={"ADMIN_DEFAULT_LANGUAGE": "en"})
    with app.test_request_context():
        assert i18n.translate("admin.common.save") == "Save"


def test_website_catalogue_is_loaded(make_app):
    # fixture_site ships translations/site.toml
    with make_app().test_request_context():
        assert i18n.translate("site.greeting") == "Ahoj"


def test_edited_catalogue_reloads_in_development(make_app, tmp_path, monkeypatch):
    site = tmp_path / "reload_site"
    (site / "translations").mkdir(parents=True)
    (site / "__init__.py").write_text("", encoding="utf-8")
    catalogue_file = site / "translations" / "site.toml"
    catalogue_file.write_text('[site.hello]\nen = "Hi"\ncs = "Ahoj"\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    app = make_app(env={"EVRIMA_ENV": "development"}, import_name="reload_site")

    catalogue_file.write_text('[site.hello]\nen = "Hello"\ncs = "Dobrý den"\n', encoding="utf-8")
    stat = catalogue_file.stat()
    os.utime(catalogue_file, (stat.st_atime, stat.st_mtime + 5))   # a clearly newer file
    app.test_client().get("/health")              # any request refreshes the catalogue
    with app.test_request_context():
        assert i18n.translate("site.hello") == "Dobrý den"
