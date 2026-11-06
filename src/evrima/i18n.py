"""Admin languages: text catalogues and the user's language.

The same catalogues hold the few public texts of the framework (the consent
banner); those are shown in the website's language, SITE_LANGUAGE, with
`site_t("key")`, never in the administrator's.

Texts live outside code, in TOML catalogues. Every key lists all supported
languages side by side, so a missing translation is visible at a glance:

    [admin.save]
    en = "Save"
    cs = "Uložit"

    [admin.items]                      # plural forms
    en = { one = "{count} item", other = "{count} items" }
    cs = { one = "{count} položka", few = "{count} položky", other = "{count} položek" }

Keys are dotted paths built from the TOML tables. The framework, each module
and the website ship their own `translations/` folder; all are merged into one
catalogue per app, and a key defined twice is an error, so modules keep to
their own prefix (e.g. `references.`).

The current language is kept in the session. Once user accounts exist, login
copies the user's stored preference into the session and the language switch
also saves it to the account (docs/framework.md, "Admin languages").
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import Flask, current_app, g, has_request_context, session

LANGUAGES = {"cs": "Čeština", "en": "English"}
# Fallback when a key lacks the requested language. English, because every key
# is written in English first.
FALLBACK_LANGUAGE = "en"
DEFAULT_LANGUAGE = "cs"
SESSION_KEY = "evrima_language"

FRAMEWORK_CATALOGUE = Path(__file__).parent / "translations"
_EXTENSION_KEY = "evrima.i18n"

# Plural category for a count, per language (the CLDR rules for whole numbers).
PLURAL_RULES = {
    "en": lambda n: "one" if n == 1 else "other",
    "cs": lambda n: "one" if n == 1 else "few" if 2 <= n <= 4 else "other",
}


class CatalogueError(ValueError):
    """Raised for a malformed catalogue file or a key defined twice."""


class Catalogue:
    """All texts of one app: key -> {language: text or {plural category: text}}."""

    def __init__(self) -> None:
        self.messages: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, Path] = {}
        self.directories: list[Path] = []
        self.loaded_at: dict[Path, float] = {}

    def load_directory(self, directory: Path) -> None:
        """Merge every `*.toml` file in `directory` into the catalogue."""
        directory = Path(directory)
        if directory not in self.directories:
            self.directories.append(directory)
        for path in sorted(directory.glob("*.toml")):
            self.load_file(path)

    def reload_if_changed(self) -> None:
        """Load every catalogue again when a file was added or edited (development).

        Templates reload on their own in development; texts should too, so an
        edited catalogue shows up without restarting the server.
        """
        current = {path: path.stat().st_mtime
                   for directory in self.directories for path in directory.glob("*.toml")}
        if current == self.loaded_at:
            return
        directories = list(self.directories)
        self.messages, self.sources, self.directories = {}, {}, []
        for directory in directories:
            self.load_directory(directory)
        self.loaded_at = current

    def load_file(self, path: Path) -> None:
        """Merge one catalogue file; raises CatalogueError on a duplicate key."""
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            raise CatalogueError(f"{path}: {error}") from error
        for key, message in _flatten(data, path):
            if key in self.messages:
                raise CatalogueError(
                    f"Text key {key!r} is defined in both {self.sources[key]} and {path}.")
            self.messages[key] = message
            self.sources[key] = path

    def text(self, key: str, language: str, count: int | None = None) -> str | None:
        """Return the raw text for `key` in `language`, falling back to English."""
        message = self.messages.get(key)
        if message is None:
            return None
        for lang in (language, FALLBACK_LANGUAGE):
            value = message.get(lang)
            if value is None:
                continue
            if isinstance(value, dict):
                category = PLURAL_RULES.get(lang, PLURAL_RULES["en"])(count or 0)
                value = value.get(category) or value.get("other")
            if value is not None:
                return value
        return None

    def missing(self) -> list[str]:
        """Return "key: language" for every key that lacks a supported language."""
        return [
            f"{key}: {lang}"
            for key, message in sorted(self.messages.items())
            for lang in LANGUAGES
            if lang not in message
        ]


def _flatten(data: Mapping[str, Any], path: Path, prefix: str = ""):
    """Yield (dotted key, message) pairs from nested TOML tables.

    A table counts as a message as soon as one of its keys is a language code;
    any other table is a namespace and is walked further.
    """
    for name, value in data.items():
        key = f"{prefix}{name}"
        if not isinstance(value, dict):
            raise CatalogueError(f"{path}: {key!r} must be a table of languages.")
        if any(lang in value for lang in LANGUAGES):
            unknown = set(value) - set(LANGUAGES)
            if unknown:
                raise CatalogueError(
                    f"{path}: {key!r} has unknown languages {sorted(unknown)}.")
            yield key, value
        else:
            yield from _flatten(value, path, f"{key}.")


def init_app(app: Flask) -> None:
    """Create the app's catalogue with the framework texts and expose the helpers.

    The website's own `translations/` folder, if it has one, is loaded too.
    Modules add theirs with `add_catalogue`.
    """
    catalogue = Catalogue()
    catalogue.load_directory(FRAMEWORK_CATALOGUE)
    website_texts = Path(app.root_path) / "translations"
    if website_texts.is_dir():
        catalogue.load_directory(website_texts)
    app.extensions[_EXTENSION_KEY] = catalogue
    catalogue.loaded_at = {path: path.stat().st_mtime
                           for directory in catalogue.directories for path in directory.glob("*.toml")}
    if app.config.get("EVRIMA_ENV") == "development":
        app.before_request(catalogue.reload_if_changed)

    app.jinja_env.globals.update(
        t=translate,
        tn=translate_plural,
        site_t=site_text,
        current_language=get_language,
        languages=LANGUAGES,
    )


def add_catalogue(app: Flask, directory: Path | str) -> None:
    """Load a module's catalogue folder into `app`."""
    catalogue = app.extensions[_EXTENSION_KEY]
    catalogue.load_directory(Path(directory))
    # Remember the files as loaded, so development does not reload them all
    # again at the first request.
    catalogue.loaded_at.update({path: path.stat().st_mtime for path in Path(directory).glob("*.toml")})


def get_catalogue() -> Catalogue:
    """The catalogue of the current app."""
    return current_app.extensions[_EXTENSION_KEY]


def get_language() -> str:
    """The language of the current request: the user's choice, else the default."""
    if not has_request_context():
        return current_app.config.get("ADMIN_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE)
    if "evrima_language" not in g:
        chosen = session.get(SESSION_KEY)
        g.evrima_language = (
            chosen if chosen in LANGUAGES
            else current_app.config.get("ADMIN_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE))
    return g.evrima_language


def set_language(language: str) -> None:
    """Remember `language` for the current user. Raises ValueError for an unsupported one."""
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language!r}")
    session[SESSION_KEY] = language
    g.evrima_language = language


def translate(key: str, **params: Any) -> str:
    """Return the text for `key` in the current language, with `{name}` placeholders filled.

    A missing key returns the key itself, so the page still renders and the gap
    is obvious; it is also logged.
    """
    return _render(key, None, params)


def translate_for(language: str, key: str, **params: Any) -> str:
    """Like `translate`, but in a given language (e.g. an e-mail in the recipient's language)."""
    return _render(key, None, params, language)


def site_text(key: str, **params: Any) -> str:
    """Like `translate`, but in the website's language (SITE_LANGUAGE): for texts visitors see."""
    return _render(key, None, params, current_app.config.get("SITE_LANGUAGE", DEFAULT_LANGUAGE))


def translate_plural(key: str, count: int, **params: Any) -> str:
    """Return the plural form of `key` matching `count`; `{count}` is available."""
    return _render(key, count, {"count": count, **params})


def _render(key: str, count: int | None, params: Mapping[str, Any], language: str | None = None) -> str:
    """Look up, fall back and format one text."""
    text = get_catalogue().text(key, language or get_language(), count)
    if text is None:
        current_app.logger.warning("Missing admin text: %s", key)
        return key
    try:
        return text.format_map(params) if params else text
    except (KeyError, IndexError, ValueError):
        # A translation with a wrong placeholder must not break the page.
        current_app.logger.warning("Bad placeholder in admin text: %s", key)
        return text


def texts_with_prefix(prefix: str) -> dict[str, str]:
    """Return {key without prefix: text} for every key under `prefix`, in the current language.

    Used to hand the admin script its texts, so JavaScript never hard-codes a string.
    """
    catalogue = get_catalogue()
    language = get_language()
    return {
        key[len(prefix):]: catalogue.text(key, language) or key
        for key in catalogue.messages
        if key.startswith(prefix)
    }
