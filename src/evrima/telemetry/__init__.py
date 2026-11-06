"""Telemetry: collecting events, buffering them in Redis, shipping them to the collector.

The protocol (what is collected and how it is sent) is the contract with the
collector and lives in the evrima-telemetry repository, docs/protocol.md. In
short: level 1 (docs/framework.md, "Telemetry") collects no personal data and
sets no cookies; server events (requests, errors, forms) come from this module,
browser events (page views, clicks) from static/evrima/js/telemetry.js through
the beacon in `telemetry.beacon`.

Level 2 is on when the website sets TELEMETRY_VISITORS to one of its consent
categories (e.g. "analytics"). After the visitor allows that category, the
script stores a random visitor id in the `evrima_vid` cookie for 13 months and
the beacon adds it to page views and clicks as `vid`, so the collector can
count unique and returning visitors. Without consent nothing changes: the
beacon ignores the cookie, and withdrawing consent deletes it.

Rules taken over from docs/framework.md:
- instrumentation never raises: a lost metric is invisible, an exception in a
  request is an outage;
- a request makes no network call for telemetry, only a Redis (or in-memory)
  write; `flask evrima telemetry ship` sends the buffer outside requests;
- labels have bounded values (the endpoint name, never the URL).

Telemetry is on when TELEMETRY_ENDPOINT is set. When it is off nothing is
collected, `telemetry_script()` puts no script tag into the page and the
beacon stores nothing (the script file itself stays a public static file).
"""

import json
import time
from datetime import UTC, datetime

from flask import Flask, current_app, g, request
from flask.signals import got_request_exception
from markupsafe import Markup

from evrima import redis_client

BUFFER_KEY = "evrima:telemetry:events"
# When the collector is unreachable for long, the oldest events go rather than
# the website's memory.
BUFFER_LIMIT = 100_000
_LOCAL_KEY = "evrima.telemetry.buffer"

# Telemetry level 2: the visitor id, 16 random bytes in URL-safe base64.
VISITOR_COOKIE = "evrima_vid"
# Thirteen months, the usual upper bound for an audience measurement cookie
# (indicative; to be verified with a lawyer). Set once and not extended.
VISITOR_MAX_AGE_DAYS = 396

# Endpoints that are not measured: static files and uploads (docs/framework.md:
# static files are not measured), the health check (polled every few seconds
# by Docker) and the beacon itself (it would count every page twice).
SKIPPED_ENDPOINTS = {"static", "evrima.static", "evrima_health.health", "evrima_media.serve",
                     "evrima_telemetry.beacon"}


def enabled() -> bool:
    """True when the website sends telemetry."""
    return bool(current_app.config.get("TELEMETRY_ENDPOINT"))


def now_iso() -> str:
    """The current UTC time in the protocol's format, with milliseconds."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def event(t: str, **fields) -> None:
    """Record one event of type `t` (protocol: `form`, `error`, …). Never raises.

    A website records its forms like this:
    `telemetry.event("form", form="contact", result="sent")`.
    """
    try:
        if not enabled():
            return
        push({"t": t, "at": now_iso(), **fields})
    except Exception:  # noqa: BLE001 - telemetry must never break a request
        current_app.logger.warning("Telemetry event %s was lost.", t, exc_info=True)


def push(item: dict) -> None:
    """Append an event to the buffer: Redis when configured, else the process."""
    data = json.dumps(item, separators=(",", ":"), ensure_ascii=False)
    client = redis_client.get_client()
    if client is None:
        buffer = current_app.extensions.setdefault(_LOCAL_KEY, [])
        buffer.append(data)
        del buffer[:-BUFFER_LIMIT]
        return
    with client.pipeline(transaction=False) as pipe:
        pipe.rpush(BUFFER_KEY, data)
        pipe.ltrim(BUFFER_KEY, -BUFFER_LIMIT, -1)
        pipe.execute()


def _status(code: int) -> str:
    """Status class for successes and redirects, the exact code for failures."""
    return f"{code // 100}xx" if code < 400 else str(code)


def _start_timer() -> None:
    g.evrima_telemetry_start = time.perf_counter()


def _record_request(response):
    """Record the request that produced `response`. Never raises."""
    try:
        if enabled() and request.endpoint not in SKIPPED_ENDPOINTS:
            start = g.get("evrima_telemetry_start")
            ms = round((time.perf_counter() - start) * 1000, 1) if start is not None else None
            push({"t": "request", "at": now_iso(), "endpoint": (request.endpoint or "(none)")[:100],
                  "method": request.method, "status": _status(response.status_code), "ms": ms})
    except Exception:  # noqa: BLE001
        current_app.logger.warning("Telemetry of a request was lost.", exc_info=True)
    return response


def _record_error(sender, exception, **extra) -> None:
    """Record an unhandled exception: its class only, never its message (it may hold personal data)."""
    event("error", endpoint=(request.endpoint or "(none)")[:100], error=type(exception).__name__[:100])


def script() -> Markup:
    """The <script> tag of the browser part, or nothing when telemetry is off."""
    from flask import url_for

    if not enabled():
        return Markup("")
    visitors = current_app.config.get("TELEMETRY_VISITORS") or ""
    if visitors:
        # Level 2: the script needs the category and the consent version to
        # read the visitor's choice from the consent cookie itself.
        return Markup(
            '<script src="{0}" data-endpoint="{1}" data-visitors="{2}" data-consent-version="{3}" '
            'data-visitor-days="{4}" defer></script>').format(
            url_for("evrima.static", filename="js/telemetry.js"), url_for("evrima_telemetry.beacon"),
            visitors, current_app.config["CONSENT_VERSION"], VISITOR_MAX_AGE_DAYS)
    return Markup('<script src="{0}" data-endpoint="{1}" defer></script>').format(
        url_for("evrima.static", filename="js/telemetry.js"), url_for("evrima_telemetry.beacon"))


def init_app(app: Flask) -> None:
    """Measure requests, record unhandled errors, add the beacon and `telemetry_script()`."""
    from evrima.telemetry import beacon

    app.before_request(_start_timer)
    app.after_request(_record_request)
    got_request_exception.connect(_record_error, app)
    app.register_blueprint(beacon.bp)
    app.jinja_env.globals["telemetry_script"] = script
