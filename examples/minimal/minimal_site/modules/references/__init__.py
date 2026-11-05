"""References: completed projects of clients, shown on the website.

A module of the example website, and the pattern new modules follow
(docs/modules.md). The website enables it:

    from minimal_site.modules import references
    app = create_app(__name__, blueprints=[pages], modules=[references])

The admin gets a "References" item. The website decides where references
appear: a route passes `references.published()` to its template, which can
use the default markup or write its own:

    {% from "references/_public.html" import reference_list %}
    {{ reference_list(items) }}
"""

from pathlib import Path

from flask import Flask
from sqlalchemy import select

from evrima.db import db
from evrima.modules import MenuItem, Module
from minimal_site.modules.references.admin import bp as admin_bp
from minimal_site.modules.references.models import Reference

__all__ = ["Reference", "module", "published"]


def published() -> list[Reference]:
    """Published references in the order set in the admin."""
    return list(db.session.scalars(
        select(Reference).where(Reference.published).order_by(Reference.position, Reference.id)))


def _setup(app: Flask) -> None:
    """Make the published references available to every website template."""
    app.jinja_env.globals["published_references"] = published


module = Module(
    name="references",
    root=Path(__file__).resolve().parent,
    blueprints=(admin_bp,),
    menu=(MenuItem("references_admin.index", "handshake", "references.nav"),),
    setup=_setup,
)
