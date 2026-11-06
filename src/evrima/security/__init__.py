"""Security layer: security headers and CSP, CSRF protection, rate limiting,
request body limits and the honeypot for public forms.

`csrf` and `limiter` are module-level so that websites and modules can import
them, e.g. `@limiter.limit("5 per minute")` on a form view or
`@csrf.exempt` on a webhook. Both are bound to the app in `init_app`.
"""

import ipaddress

from flask import Flask, current_app, request
from flask_limiter import Limiter
from flask_wtf.csrf import CSRFProtect

from evrima.security import headers, honeypot

# Every POST, PUT, PATCH and DELETE request needs a valid CSRF token, unless a
# view is explicitly exempted.
csrf = CSRFProtect()

def client_key() -> str:
    """The client for rate limits and the login lockout: its IPv4 address, or its IPv6 /64.

    One IPv6 customer usually gets a whole /64 (2^64 addresses), so counting
    each IPv6 address apart let a single machine rotate addresses and skip
    every per-IP limit (security audit 2026-11-06). The remote address is the
    real client IP because the app factory applies ProxyFix behind Caddy.
    """
    address = request.remote_addr or ""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 4:
        return str(ip)
    if ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    return str(ipaddress.ip_network(f"{ip}/64", strict=False))


def same_origin_request() -> bool:
    """True when the browser says the request comes from the website's own page.

    For the few endpoints that cannot carry a CSRF token (the telemetry
    beacon) or should not need one (the consent banner, docs/framework.md,
    "Consent banner"). Without this check any other website could make its
    visitors' browsers post here: fake page views spread over so many
    addresses that the per-IP limit never applies (code review 2026-11-06),
    or a forged "accept all" consent. Browsers send `Sec-Fetch-Site` on every
    such request; `Origin` is the fallback for the few that do not. A request
    with neither is not from a browser page and is refused.
    """
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        return site == "same-origin"
    origin = request.headers.get("Origin")
    return origin is not None and origin == request.host_url.rstrip("/")


# No default limits: each form sets its own, because a sensible limit for a
# contact form on one website can be far too low or too high on another
# (docs/framework.md, decided after the audit).
limiter = Limiter(client_key)


def body_limit(max_bytes: int):
    """Let a view accept a request body of up to `max_bytes` (capped by MAX_CONTENT_LENGTH).

    For views that take files, e.g. a form with an attachment:
    `@body_limit(10 * 1024 * 1024)`. Every other view gets BODY_LIMIT, or
    ADMIN_BODY_LIMIT under /admin/. Goes on the view function in any order with
    other decorators that use functools.wraps.
    """
    def mark(view):
        view.evrima_body_limit = max_bytes
        return view
    return mark


def _apply_body_limit() -> None:
    """Set the body limit of this request before anything reads the body.

    Registered before CSRF protection, which reads the form in its own
    before_request hook; a larger body then fails with 413.
    """
    config = current_app.config
    view = current_app.view_functions.get(request.endpoint)
    limit = getattr(view, "evrima_body_limit", None)
    if limit is None:
        limit = config["ADMIN_BODY_LIMIT"] if request.path.startswith("/admin/") else config["BODY_LIMIT"]
    request.max_content_length = min(limit, config["MAX_CONTENT_LENGTH"])


def init_app(app: Flask) -> None:
    """Enable headers, body limits, CSRF protection, the rate limiter and the honeypot for `app`."""
    headers.init_app(app)
    app.before_request(_apply_body_limit)
    csrf.init_app(app)
    limiter.init_app(app)
    honeypot.init_app(app)
