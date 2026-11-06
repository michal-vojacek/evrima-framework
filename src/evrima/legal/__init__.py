"""Skeletons of legal pages: the privacy policy and the cookies page.

The framework gives the structure, the sections every such page needs and the
parts it knows itself (the framework's own cookies, telemetry); the website
fills in what only it knows: who the controller is, what it processes and why,
its processors, retention, third-party cookies (docs/framework.md, "Legal
pages", decided 2026-11-06). The texts are indicative only and should be
checked by a lawyer before a website goes live.

Switched on by the website's `LEGAL_PAGES`: `["privacy", "cookies"]` for the
default addresses in the website's language (DEFAULT_PATHS), or
`{"privacy": "/ochrana-udaju", "cookies": "/cookies"}` for its own.

Each page is rendered from `legal/<page>.html` in the website, which normally
extends the skeleton in its language, `evrima/legal/<page>.<language>.html`,
and fills its blocks; without it, the skeleton itself, with visible "fill in"
marks. The skeleton extends the website's layout (SITE_LAYOUT).

In templates: `legal_url("privacy")`, None when the page is off.
"""

from flask import Blueprint, Flask, current_app, render_template, url_for

PAGES = ("privacy", "cookies")
DEFAULT_PATHS = {
    "cs": {"privacy": "/zasady-ochrany-osobnich-udaju", "cookies": "/cookies"},
    "en": {"privacy": "/privacy", "cookies": "/cookies"},
}


def paths(config) -> dict[str, str]:
    """{page: address} of the website's legal pages."""
    pages = config.get("LEGAL_PAGES") or []
    if isinstance(pages, dict):
        return dict(pages)
    defaults = DEFAULT_PATHS[config["SITE_LANGUAGE"]]
    return {page: defaults[page] for page in pages}


def url(page: str) -> str | None:
    """The address of a legal page, or None when the website does not use it."""
    if page not in paths(current_app.config):
        return None
    return url_for(f"evrima_legal.{page}")


def _context() -> dict:
    """What the skeletons know about the website: which framework features set cookies or collect data."""
    from evrima import consent, telemetry
    from evrima.auth.sessions import SESSION_COOKIE

    config = current_app.config
    return {
        "session_cookie": config.get("SESSION_COOKIE_NAME", "session"),
        "admin_cookie": SESSION_COOKIE,
        "consent_cookie": consent.COOKIE,
        "consent_enabled": consent.enabled(),
        "consent_categories": consent.categories(),
        "telemetry_enabled": telemetry.enabled(),
        "visitor_cookie": telemetry.VISITOR_COOKIE,
        "visitors_category": config.get("TELEMETRY_VISITORS") or "",
        "privacy_url": url("privacy"),
        "cookies_url": url("cookies"),
    }


def _view(page: str):
    def show():
        language = current_app.config["SITE_LANGUAGE"]
        return render_template([f"legal/{page}.html", f"evrima/legal/{page}.{language}.html"], **_context())
    show.__name__ = page
    show.__doc__ = f"The {page} page."
    return show


def init_app(app: Flask) -> None:
    """Add the website's legal pages at their addresses and the `legal_url` helper."""
    # A blueprint per app: the addresses are the website's settings.
    bp = Blueprint("evrima_legal", __name__)
    for page, path in paths(app.config).items():
        bp.add_url_rule(path, page, _view(page), methods=["GET"])
    app.register_blueprint(bp)
    app.jinja_env.globals["legal_url"] = url
