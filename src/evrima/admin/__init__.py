"""Admin frame: start page, language switch and the /admin/design cookbook.

The admin lives under /admin, behind the login (evrima.auth.protect). Its
templates are in templates/evrima/admin/ and are not meant to be overridden by
websites (docs/framework.md, decided after the audit): a change to the admin
belongs in the framework. Modules plug their screens in with their own
protected blueprints.
"""

from flask import Blueprint, Flask, abort, flash, redirect, render_template, request

from evrima import i18n
from evrima.admin import modal
from evrima.admin.navigation import safe_next
from evrima.auth import protect
from evrima.auth.sessions import current_admin
from evrima.db import db
from evrima.version import get_version

bp = Blueprint("evrima_admin", __name__, url_prefix="/admin")
# The language switch also serves the login page, so it stays open.
protect(bp, public={"evrima_admin.set_language"})


def init_app(app: Flask) -> None:
    """Register the admin blueprint and the template helpers it needs."""
    app.register_blueprint(bp)
    app.jinja_env.globals.update(
        modal_state=modal.state,
        admin_js_texts=lambda: i18n.texts_with_prefix("admin.js."),
        evrima_version=get_version,
    )


@bp.get("/")
def index():
    """The admin start page. Modules will add their overview cards here."""
    return render_template("evrima/admin/index.html")


@bp.get("/design")
def design():
    """The admin design cookbook: every component on one page (logged-in administrators only)."""
    return render_template("evrima/admin/design.html")


@bp.post("/language")
def set_language():
    """Switch the admin language, save it to the account, return to the previous page."""
    language = request.form.get("language", "")
    try:
        i18n.set_language(language)
    except ValueError:
        abort(400)
    admin = current_admin()
    if admin is not None:
        admin.language = language
        db.session.commit()
    flash(i18n.translate("admin.language.saved"), "success")
    return redirect(safe_next(request.form.get("next")))
