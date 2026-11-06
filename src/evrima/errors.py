"""Default error pages.

Each error is rendered from the first template that exists:

1. `errors/<code>.html` in the website (e.g. its own 404 page),
2. `errors/error.html` in the website (one page for every error),
3. `evrima/errors/error.html`, the framework's plain fallback.

So a website overrides error pages simply by adding templates, without
registering handlers of its own.
"""

from flask import Flask, Response, render_template
from flask.globals import request_ctx
from werkzeug.exceptions import HTTPException, InternalServerError

# The errors a visitor can realistically run into. Anything else falls through
# to Werkzeug's own minimal page.
HANDLED_CODES = (400, 403, 404, 405, 413, 429, 500)


def register(app: Flask) -> None:
    """Install the error handlers on `app`."""
    for code in HANDLED_CODES:
        app.register_error_handler(code, _render_error)


def _render_error(error: HTTPException):
    """Render the most specific error template available for `error`."""
    if not isinstance(error, HTTPException):
        # Flask wraps unhandled exceptions in InternalServerError before
        # calling the 500 handler; this only guards the template, which needs
        # code, name and description, against anything else slipping through.
        error = InternalServerError()
    if request_ctx.url_adapter is None:
        # The request never reached routing, typically a Host outside
        # SITE_HOSTS (a scanner, or upper case: Caddy matches hosts without
        # regard to case, Flask does not). The website's error page calls
        # url_for, which cannot work here, and used to turn every such 400 into
        # a bare 500 with two tracebacks (security audit 2026-11-06).
        return Response(f"{error.code} {error.name}", error.code, mimetype="text/plain")
    templates = [f"errors/{error.code}.html", "errors/error.html", "evrima/errors/error.html"]
    return render_template(templates, error=error), error.code
