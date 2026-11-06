"""Files and markup for search engines and AI assistants: robots.txt, sitemap.xml,
/.well-known/security.txt, canonical URLs and schema.org structured data.

The website decides the content through its config (passed to create_app as
overrides, they are website decisions rather than environment settings):

- `SITE_URL`: the canonical address, e.g. `https://example.com`. Default: the
  first of SITE_HOSTS over HTTPS; outside production the address of the request.
- `SITEMAP`: endpoints of the website's public pages (without URL arguments),
  e.g. `["pages.home", "pages.references"]`. No list, no sitemap.
- `ROBOTS_BLOCKED_AGENTS`: crawlers kept out of the whole website, e.g. AI
  training crawlers (`["GPTBot", "CCBot", "Google-Extended"]`). Everyone else
  may crawl everything except the admin.
- `SECURITY_CONTACT`: where security problems are reported (`mailto:…` or
  `https://…`), required for security.txt (RFC 9116). No contact, no file.
- `SECURITY_LANGUAGES`: preferred languages of reports, default `cs, en`.

In templates: `{{ canonical_url() }}` and `{{ data | json_ld }}`.
"""

import json
from datetime import UTC, datetime, timedelta

from flask import Blueprint, Flask, Response, abort, current_app, request, url_for
from markupsafe import Markup

bp = Blueprint("evrima_seo", __name__)

# RFC 9116 asks for Expires less than a year ahead and for the file to be kept
# current. Computed on each request, it never goes stale; half a year is what
# a scanner sees as a maintained file.
SECURITY_TXT_VALIDITY = timedelta(days=180)


def site_url() -> str:
    """The canonical address of the website, without a trailing slash."""
    config = current_app.config
    if config.get("SITE_URL"):
        return config["SITE_URL"].rstrip("/")
    if config.get("EVRIMA_ENV") == "production" and config.get("SITE_HOSTS"):
        return f"https://{config['SITE_HOSTS'][0]}"
    return request.host_url.rstrip("/")


def canonical_url() -> str:
    """The canonical URL of the current page: the site's address and the path, no query string."""
    return site_url() + request.path


def json_ld(data) -> Markup:
    r"""schema.org data as a <script type="application/ld+json"> block.

    `<`, `>` and `&` are written as JSON escapes (`\u003c` …), the same as
    Django's json_script: escaping only `</` still let `<!--<script>` in a value
    switch the HTML parser into a state where the real `</script>` no longer
    ends the block (code review 2026-11-06). JSON readers decode the escapes
    back. The block is data, not a script: browsers do not run it, so the
    strict CSP does not block it (checked in Chrome on 2026-11-05).
    """
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026"))
    return Markup(f'<script type="application/ld+json">{text}</script>')


def _text(body: str) -> Response:
    return Response(body, mimetype="text/plain")


@bp.get("/robots.txt")
def robots():
    """Crawling rules: everything except the admin; blocked agents nothing."""
    lines = []
    for agent in current_app.config.get("ROBOTS_BLOCKED_AGENTS") or []:
        lines += [f"User-agent: {agent}", "Disallow: /", ""]
    lines += ["User-agent: *", "Allow: /", "Disallow: /admin/", ""]
    if current_app.config.get("SITEMAP"):
        lines.append(f"Sitemap: {site_url()}{url_for('evrima_seo.sitemap')}")
    return _text("\n".join(lines).rstrip("\n") + "\n")


@bp.get("/sitemap.xml")
def sitemap():
    """The website's public pages."""
    endpoints = current_app.config.get("SITEMAP") or []
    if not endpoints:
        abort(404)
    base = site_url()
    urls = "".join(f"<url><loc>{base}{url_for(endpoint)}</loc></url>" for endpoint in endpoints)
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    return Response(body, mimetype="application/xml")


@bp.get("/.well-known/security.txt")
def security_txt():
    """Where to report a security problem (RFC 9116)."""
    contact = current_app.config.get("SECURITY_CONTACT")
    if not contact:
        abort(404)
    expires = (datetime.now(UTC) + SECURITY_TXT_VALIDITY).replace(microsecond=0)
    lines = [
        f"Contact: {contact}",
        f"Expires: {expires.isoformat().replace('+00:00', 'Z')}",
        f"Preferred-Languages: {current_app.config.get('SECURITY_LANGUAGES') or 'cs, en'}",
        f"Canonical: {site_url()}{url_for('evrima_seo.security_txt')}",
    ]
    return _text("\n".join(lines) + "\n")


def init_app(app: Flask) -> None:
    """Serve the files and add `canonical_url()` and the `json_ld` filter to templates."""
    app.register_blueprint(bp)
    app.jinja_env.globals["canonical_url"] = canonical_url
    app.jinja_env.filters["json_ld"] = json_ld
