"""The beacon: browser events (page views, clicks) sent by static/evrima/js/telemetry.js.

The browser sends to the website itself, never to a third party. Every event
is checked here against the protocol (docs/protocol.md in evrima-telemetry):
only known types and fields, bounded strings, no query strings. Anything else
is dropped silently. The answer is always 204: the script does not wait for it
and a bot learns nothing.
"""

import json
import re

from flask import Blueprint, Response, current_app, request

from evrima import telemetry
from evrima.security import csrf, limiter, same_origin_request

bp = Blueprint("evrima_telemetry", __name__)

MAX_BODY = 2048                      # one event is a few hundred bytes
LABEL = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
HOST = re.compile(r"^[a-z0-9.-]{1,100}$")
DEVICES = {"mobile", "tablet", "desktop"}
CLICK_KINDS = {"tel", "mailto", "external", "track"}
MAX_MS = 600_000                     # ten minutes: anything longer is not a page load
VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")


def _ms(value):
    """A timing in whole milliseconds, or None when absent or implausible."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if 0 <= value <= MAX_MS else None


def _host(value) -> str:
    """A host name, lower case, without `www.`; empty when it does not look like one."""
    if not isinstance(value, str):
        return ""
    host = value.strip().lower().removeprefix("www.")
    return host if HOST.match(host) else ""


def clean(data) -> dict | None:
    """The event as the protocol allows it, or None when it is not a valid event."""
    if not isinstance(data, dict):
        return None
    kind = data.get("t")
    if kind == "pageview":
        path = data.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            return None
        path = path.split("?", 1)[0].split("#", 1)[0][:200]
        device = data.get("device")
        item = {"t": "pageview", "path": path, "entry": data.get("entry") is True,
                "ref": _host(data.get("ref")), "device": device if device in DEVICES else "desktop"}
        for key in ("ttfb", "dom", "load"):
            value = _ms(data.get(key))
            if value is not None:
                item[key] = value
        return item
    if kind == "click":
        click_kind = data.get("kind")
        if click_kind not in CLICK_KINDS:
            return None
        label = data.get("label")
        item = {"t": "click", "kind": click_kind, "label": label if isinstance(label, str) and LABEL.match(label) else ""}
        if click_kind == "external":
            host = _host(data.get("host"))
            if not host:
                return None
            item["host"] = host
            item["label"] = item["label"] or host[:40]
        elif click_kind == "track" and not item["label"]:
            return None
        return item
    return None


def visitor_id() -> str | None:
    """The visitor id for telemetry level 2, or None.

    Only when the website uses level 2 and the visitor allowed its consent
    category: the consent is checked here, from the request's own cookie, not
    trusted from the script.
    """
    from evrima import consent

    category = current_app.config.get("TELEMETRY_VISITORS")
    if not category or not consent.given(category):
        return None
    value = request.cookies.get(telemetry.VISITOR_COOKIE, "")
    return value if VISITOR_ID.match(value) else None


def _body() -> bytes | None:
    """The request body if it is at most MAX_BODY bytes, else None.

    Read from the stream with a cap, so a chunked body without Content-Length
    is not first read whole (up to MAX_CONTENT_LENGTH) and only then cut.
    """
    if (request.content_length or 0) > MAX_BODY:
        return None
    body = request.stream.read(MAX_BODY + 1)
    return body if 0 < len(body) <= MAX_BODY else None


@bp.post("/_evrima/t")
@csrf.exempt                          # sendBeacon cannot send a CSRF token; the beacon changes nothing but counters
@limiter.limit("120 per minute")      # a page view and a few clicks a minute is plenty for a person
def beacon():
    """Check one browser event and put it into the buffer."""
    if telemetry.enabled() and same_origin_request():
        body = _body()
        try:
            item = clean(json.loads(body)) if body is not None else None
        except ValueError:
            item = None
        if item is not None:
            try:
                vid = visitor_id()
                if vid is not None:
                    item["vid"] = vid
                telemetry.push({**item, "at": telemetry.now_iso()})
            except Exception:  # noqa: BLE001 - telemetry never fails a request
                pass
    return Response(status=204)
