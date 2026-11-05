"""Modules: how a website's modules plug into an Evrima app.

The framework ships no content modules. Each website writes the modules its
client needs (references, a price list, a gallery...) in its own `modules/`
folder, following docs/modules.md. A module is a package with a
`module = Module(...)` description, and the website enables it explicitly
when it builds its app:

    from mysite.modules import references
    app = create_app(__name__, blueprints=[pages], modules=[references])

Registering a module loads its text catalogue (`translations/`), adds its
migration branch (`migrations/versions/`, branch label = module name),
registers its blueprints and adds its items to the admin menu. The module's
templates come with its blueprint (`template_folder`), under
`templates/<module>/`, so names cannot clash.

Every table of a module carries its name in `info`, so migrations created
for one branch never touch another branch's tables (`evrima.db.migrations`):

    __table_args__ = {"info": {"evrima_module": "references"}}

Nothing is discovered automatically: a misspelt or missing module fails at
startup, not silently at the first request (docs/framework.md, "Modules").
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from flask import Blueprint, Flask, request

from evrima import i18n
from evrima.config import ConfigError
from evrima.db import migrations

_EXTENSION_KEY = "evrima.modules"
# The name is also a migration branch label, a catalogue key prefix and a
# template folder, so it is kept to plain lowercase identifiers. "evrima"
# and "website" are the framework's and the website's own branches.
NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,39}")
RESERVED_NAMES = frozenset({"evrima", "website"})


@dataclass(frozen=True)
class MenuItem:
    """One link in the admin menu.

    `label` is a catalogue key. The item is highlighted on every page of the
    endpoint's blueprint (the list and its forms alike).
    """

    endpoint: str
    icon: str
    label: str


@dataclass(frozen=True)
class Module:
    """What a module brings into an app.

    name: unique within the app; also the label of its migration branch.
    root: the module's package folder (holds translations/ and migrations/).
    blueprints: admin screens (protected with evrima.auth.protect) and,
        for a website's own module, public routes.
    menu: links in the admin menu, in the "Content" section.
    setup: optional hook called with the app, e.g. for template helpers.
    """

    name: str
    root: Path
    blueprints: tuple[Blueprint, ...] = ()
    menu: tuple[MenuItem, ...] = ()
    setup: Callable[[Flask], None] | None = None


def register(app: Flask, modules: Iterable[Module | ModuleType]) -> None:
    """Enable `modules` in `app`. Accepts Module objects or packages with `module`."""
    enabled: dict[str, Module] = {}
    for item in modules:
        module = getattr(item, "module", item)
        if not isinstance(module, Module):
            raise ConfigError([f"{item!r} is not an Evrima module (it has no `module = Module(...)`)."])
        if module.name in enabled:
            raise ConfigError([f"Module {module.name!r} is enabled twice."])
        _check(module)
        enabled[module.name] = module

        translations = module.root / "translations"
        if translations.is_dir():
            i18n.add_catalogue(app, translations)
        versions = module.root / "migrations" / "versions"
        if versions.is_dir():
            migrations.add_migrations(app, versions)
        for blueprint in module.blueprints:
            app.register_blueprint(blueprint)
        if module.setup is not None:
            module.setup(app)

    app.extensions[_EXTENSION_KEY] = enabled
    app.jinja_env.globals["admin_menu"] = admin_menu


def _check(module: Module) -> None:
    """Refuse a module whose name or admin screens would cause trouble later."""
    if not NAME_PATTERN.fullmatch(module.name) or module.name in RESERVED_NAMES:
        raise ConfigError([
            f"Module name {module.name!r} is not allowed: use lowercase letters, digits and "
            f"underscores, starting with a letter, and not {' or '.join(sorted(RESERVED_NAMES))}."])
    for blueprint in module.blueprints:
        if (blueprint.url_prefix or "").startswith("/admin") and not getattr(blueprint, "evrima_protected", False):
            raise ConfigError([
                f"Blueprint {blueprint.name!r} of module {module.name!r} serves admin pages "
                "without login: call evrima.auth.protect() on it."])


def enabled_modules(app: Flask) -> dict[str, Module]:
    """The modules enabled in `app`, by name, in the order they were given."""
    return app.extensions.get(_EXTENSION_KEY, {})


def admin_menu() -> list[tuple[MenuItem, bool]]:
    """Menu items of the enabled modules, each with whether it is the current page."""
    from flask import current_app

    current = (request.endpoint or "").split(".")[0]
    return [(item, item.endpoint.split(".")[0] == current)
            for module in enabled_modules(current_app).values() for item in module.menu]
