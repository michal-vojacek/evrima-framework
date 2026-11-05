"""Security layer: security headers and CSP, CSRF protection and rate limiting.

`csrf` and `limiter` are module-level so that websites and modules can import
them, e.g. `@limiter.limit("5 per minute")` on a form view or
`@csrf.exempt` on a webhook. Both are bound to the app in `init_app`.
"""

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from evrima.security import headers

# Every POST, PUT, PATCH and DELETE request needs a valid CSRF token, unless a
# view is explicitly exempted.
csrf = CSRFProtect()

# No default limits: each form sets its own, because a sensible limit for a
# contact form on one website can be far too low or too high on another
# (docs/framework.md, decided after the audit). The remote address is the real
# client IP because the app factory applies ProxyFix behind Caddy.
limiter = Limiter(get_remote_address)


def init_app(app: Flask) -> None:
    """Enable headers, CSRF protection and the rate limiter for `app`."""
    headers.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
