"""Consent banner: the groundwork for asking visitors about cookies.

The framework stores the visitor's choice per category and gives the website
the banner, the settings page, a small script and texts (docs/framework.md,
"Consent banner", decided 2026-11-06). It does not know any third-party
service: which service needs which category, and how it is told (left out of
the page, Google's consent mode, …), is decided by the website, because one
service can depend on several categories at once.

Switched on by the website's `CONSENT_CATEGORIES`, e.g. `["analytics",
"marketing"]`; necessary cookies are always allowed and never listed. Every
category needs the texts `consent.category.<name>.name` and `.description`;
the framework ships them for `analytics`, `marketing` and `preferences`, a
website adds others in its own catalogue.

The choice lives in the `evrima_consent` cookie: `v<CONSENT_VERSION>` followed
by the allowed categories, e.g. `v1.analytics`. It is not signed: a visitor
who edits it changes only their own choice. Raising CONSENT_VERSION makes every
earlier choice invalid, so everyone is asked again.

In templates:
- `{{ consent_head() }}` in `<head>`: the banner's stylesheet and script;
- `{{ consent_banner() }}` before `</body>`: the banner, visible until the
  visitor decides;
- `consent("analytics")`: whether the visitor allowed a category;
- `consent_settings_url()`: the settings page, for a link in the footer;
  with `data-evrima-consent-open` the script opens the banner in place instead.

In the browser: `evrimaConsent.has("analytics")`, `evrimaConsent.categories()`
and the `evrima:consent` event on `document` after every change, with
`event.detail.categories`.
"""

import re
from datetime import timedelta

from flask import (Blueprint, Flask, abort, current_app, g, jsonify, redirect, render_template, request,
                   url_for)
from markupsafe import Markup

from evrima.config import ConfigError
from evrima.security import csrf, limiter, same_origin_request

COOKIE = "evrima_consent"
# Twelve months, then the visitor is asked again (indicative, following the
# common European practice; to be verified with a lawyer).
MAX_AGE = timedelta(days=365)
CATEGORY_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
# Categories whose texts the framework ships (translations/consent.toml).
KNOWN_CATEGORIES = ("analytics", "marketing", "preferences")
CHOICES = ("all", "none", "selected")

bp = Blueprint("evrima_consent", __name__)


def enabled() -> bool:
    """True when the website asks for consent."""
    return bool(current_app.config.get("CONSENT_CATEGORIES"))


def categories() -> list[str]:
    """The website's consent categories, without the necessary ones."""
    return list(current_app.config.get("CONSENT_CATEGORIES") or [])


def _version_tag() -> str:
    return f"v{current_app.config['CONSENT_VERSION']}"


def parse(value: str | None) -> frozenset[str] | None:
    """The allowed categories stored in a cookie value, or None when it is no valid current choice."""
    if not value:
        return None
    version, *allowed = value.split(".")
    if version != _version_tag():
        return None
    known = set(categories())
    return frozenset(c for c in allowed if c in known)


def choice() -> frozenset[str] | None:
    """The current visitor's allowed categories, or None when they have not decided (yet)."""
    if not enabled():
        return None
    if "evrima_consent" not in g:
        g.evrima_consent = parse(request.cookies.get(COOKIE))
    return g.evrima_consent


def decided() -> bool:
    """True when the visitor has made a choice valid for the current CONSENT_VERSION."""
    return choice() is not None


def given(category: str) -> bool:
    """True when the visitor allowed `category`. Always False when the banner is off."""
    allowed = choice()
    return allowed is not None and category in allowed


def cookie_value(allowed) -> str:
    """The cookie value for a choice; categories in the website's order."""
    return ".".join([_version_tag(), *[c for c in categories() if c in allowed]])


def _safe_next(target: str | None) -> str:
    """A path on this website to return to; anything else goes to the home page."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def _current_path() -> str:
    """The current page with its query string, to come back to after saving."""
    return request.full_path.rstrip("?") if request.query_string else request.path


def _form_context(next_url: str, open_details: bool) -> dict:
    """What the banner's form needs to render."""
    from evrima import legal

    allowed = choice() or frozenset()
    return {
        "consent_categories": categories(),
        "consent_allowed": allowed,
        "consent_next": next_url,
        "consent_open": open_details,
        "cookies_url": legal.url("cookies"),
    }


def banner() -> Markup:
    """The banner, hidden once the visitor has decided (the script can open it again).

    Nothing when the banner is off, and nothing on the settings page, which
    shows the same form itself.
    """
    if not enabled() or request.endpoint == "evrima_consent.settings":
        return Markup("")
    context = _form_context(_current_path(), open_details=False)
    return Markup(render_template(
        ["consent/banner.html", "evrima/consent/banner.html"], consent_hidden=decided(), **context))


def head() -> Markup:
    """The banner's stylesheet and script, or nothing when the banner is off."""
    if not enabled():
        return Markup("")
    return Markup(
        '<link rel="stylesheet" href="{0}">\n<script src="{1}" data-version="{2}" defer></script>').format(
        url_for("evrima.static", filename="css/consent.css"),
        url_for("evrima.static", filename="js/consent.js"),
        current_app.config["CONSENT_VERSION"])


def settings_url() -> str | None:
    """The settings page, or None when the banner is off."""
    return url_for("evrima_consent.settings") if enabled() else None


@bp.get("/_evrima/consent")
def settings():
    """The settings page: the banner's form, open, for visitors without JavaScript and for the footer link."""
    if not enabled():
        abort(404)
    context = _form_context(_safe_next(request.args.get("next")), open_details=True)
    return render_template(["consent/settings.html", "evrima/consent/settings.html"], **context)


@bp.post("/_evrima/consent")
# No CSRF token: a token would need the session cookie, which would then be
# set for every visitor on every page just to show the banner. Refusing
# requests from other websites (same_origin_request) prevents a forged
# "accept all" just as well.
@csrf.exempt
@limiter.limit("30 per minute")
def save():
    """Store the visitor's choice; JSON for the script, else a redirect back to the page."""
    if not enabled():
        abort(404)
    if not same_origin_request():
        abort(403)
    action = request.form.get("choice")
    if action not in CHOICES:
        abort(400)
    if action == "all":
        allowed = set(categories())
    elif action == "none":
        allowed = set()
    else:
        allowed = set(request.form.getlist("category")) & set(categories())

    wants_json = request.accept_mimetypes.best == "application/json"
    if wants_json:
        response = jsonify(categories=[c for c in categories() if c in allowed])
    else:
        response = redirect(_safe_next(request.form.get("next")), 303)
    config = current_app.config
    # Readable by the page's script (not HttpOnly): the choice is no secret,
    # and the script must know it on cached or already loaded pages.
    response.set_cookie(COOKIE, cookie_value(allowed), max_age=int(MAX_AGE.total_seconds()), path="/",
                        secure=config["SESSION_COOKIE_SECURE"], httponly=False, samesite="Lax")
    visitors = config.get("TELEMETRY_VISITORS")
    if visitors and visitors not in allowed:
        # Withdrawn consent removes the telemetry visitor cookie at once
        # (telemetry level 2, docs/framework.md, "Telemetry").
        from evrima.telemetry import VISITOR_COOKIE
        response.delete_cookie(VISITOR_COOKIE, path="/")
    return response


def _missing_texts(app: Flask) -> list[str]:
    """Categories without their texts in the catalogue."""
    from evrima.i18n import _EXTENSION_KEY

    messages = app.extensions[_EXTENSION_KEY].messages
    return [
        f"CONSENT_CATEGORIES: {category!r} needs the texts consent.category.{category}.name and "
        f".description in the website's translations."
        for category in app.config.get("CONSENT_CATEGORIES") or []
        if f"consent.category.{category}.name" not in messages
        or f"consent.category.{category}.description" not in messages
    ]


def init_app(app: Flask) -> None:
    """Add the consent endpoints and template helpers; check that every category has its texts."""
    problems = _missing_texts(app)
    if problems:
        raise ConfigError(problems)
    app.register_blueprint(bp)
    app.jinja_env.globals.update(
        consent=given,
        consent_head=head,
        consent_banner=banner,
        consent_settings_url=settings_url,
    )
