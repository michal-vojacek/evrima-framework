"""Admin login: accounts, e-mailed PIN, trusted devices, TOTP, administrators.

Public pages (login, verification, forgotten password) live in `views`; the
account page and the management of administrators in `accounts`, behind the
login. Every admin blueprint, including modules' ones, protects itself with
`protect(blueprint)`.
"""

from collections.abc import Iterable

from flask import Blueprint, Flask, redirect, request, url_for

from evrima.auth.sessions import current_admin


def init_app(app: Flask) -> None:
    """Register the login pages, the account pages and the template helper."""
    from evrima.auth import accounts, views

    app.register_blueprint(views.bp)
    app.register_blueprint(accounts.bp)
    app.jinja_env.globals["admin_user"] = current_admin


def protect(blueprint: Blueprint, public: Iterable[str] = ()) -> None:
    """Require a logged-in administrator for every view of `blueprint`.

    `public` lists endpoints that stay open (e.g. the language switch, which
    also serves the login page). An anonymous visitor is sent to the login
    page and comes back to the page they wanted afterwards.
    """
    open_endpoints = set(public)
    # Read by evrima.modules.register, which refuses an unprotected admin
    # blueprint: forgetting protect() would publish the module's admin.
    blueprint.evrima_protected = True

    @blueprint.before_request
    def _require_admin():
        if request.endpoint in open_endpoints or current_admin() is not None:
            return None
        target = request.full_path.rstrip("?") if request.method == "GET" else None
        return redirect(url_for("evrima_auth.login", next=target))
