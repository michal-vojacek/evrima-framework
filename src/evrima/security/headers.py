"""Security headers added to every response.

The policy is strict by default: scripts, styles, images, fonts and requests
may only come from the website itself, and nothing may be inlined. That is what
lets a website score at the top of Mozilla Observatory, and it is why templates
must not contain inline scripts, `style="…"` attributes or `onclick=` handlers
(docs/framework.md, "Security baseline").
"""

from collections.abc import Mapping, Sequence

from flask import Flask, Response, request

DEFAULT_CSP: dict[str, tuple[str, ...]] = {
    "default-src": ("'self'",),
    "script-src": ("'self'",),
    "style-src": ("'self'",),
    "img-src": ("'self'",),
    "font-src": ("'self'",),
    "connect-src": ("'self'",),
    "object-src": ("'none'",),
    "base-uri": ("'self'",),
    "form-action": ("'self'",),
    "frame-ancestors": ("'none'",),
}

# Browser features no simple website needs. Denying them means a compromised
# third-party asset could not use them either.
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

# One year. includeSubDomains follows the hosting policy; preload is
# deliberately absent, because leaving the preload list takes months.
HSTS = "max-age=31536000; includeSubDomains"


def build_csp(extra: Mapping[str, Sequence[str]] | None = None) -> str:
    """Return the Content-Security-Policy header value.

    `extra` adds sources to directives (or new directives) on top of the
    default policy; it can widen the policy for a website that needs, say, an
    external map, but never removes the defaults.
    """
    policy = {directive: list(sources) for directive, sources in DEFAULT_CSP.items()}
    for directive, sources in (extra or {}).items():
        merged = policy.setdefault(directive, [])
        for source in sources:
            if source not in merged:
                merged.append(source)
    return "; ".join(f"{directive} {' '.join(sources)}" for directive, sources in policy.items())


ADMIN_PATH = "/admin"
# The admin previews images chosen for upload before they are sent; the
# browser hands them to the page as blob: URLs, which only the page's own
# script can create. Public pages do not need this and keep the strict policy.
ADMIN_CSP_EXTRA = {"img-src": ("blob:",)}


def init_app(app: Flask) -> None:
    """Attach the security headers to every response of `app`."""
    # Built once: the policy does not change while the app runs.
    extra = app.config.get("CSP") or {}
    csp = build_csp(extra)
    admin_extra = {directive: list(extra.get(directive, ())) for directive in extra}
    for directive, sources in ADMIN_CSP_EXTRA.items():
        admin_extra.setdefault(directive, []).extend(sources)
    admin_csp = build_csp(admin_extra)
    send_hsts = app.config.get("EVRIMA_ENV") == "production"

    @app.after_request
    def _security_headers(response: Response) -> Response:
        """Add the headers unless a view has already set its own value."""
        headers = response.headers
        # setdefault rather than assignment: a single view with a genuine need
        # (e.g. an embeddable widget) can set its own header without the
        # framework silently overwriting it.
        in_admin = request.path == ADMIN_PATH or request.path.startswith(ADMIN_PATH + "/")
        headers.setdefault("Content-Security-Policy", admin_csp if in_admin else csp)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if send_hsts:
            headers.setdefault("Strict-Transport-Security", HSTS)
        return response
