"""Shared Redis connection of the website.

Redis is used for form rate limiting (Flask-Limiter keeps its own connection)
and, later, as the telemetry buffer. Outside production `REDIS_URL` may be
`memory://` or empty, in which case there is no client and callers skip Redis.
"""

import redis
from flask import Flask, current_app

from evrima.config import REDIS_SCHEMES

_EXTENSION_KEY = "evrima.redis"


def init_app(app: Flask) -> None:
    """Create the Redis client for `app`, or record that there is none."""
    url = app.config.get("REDIS_URL") or ""
    client = None
    if url.startswith(REDIS_SCHEMES):
        # Short timeouts: when Redis hangs, a request should lose a feature
        # (a counter, a metric), not wait for seconds and pile up workers.
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    app.extensions[_EXTENSION_KEY] = client


def get_client() -> redis.Redis | None:
    """The Redis client of the current app, or None when Redis is not configured."""
    return current_app.extensions.get(_EXTENSION_KEY)
