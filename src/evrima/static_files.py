"""Static files: fingerprinted URLs and cache headers.

Every `url_for("static", filename=…)` (the website's files and the
framework's `evrima.static`) gets `?v=<hash of the file's content>`. A request
with the right hash may be cached by browsers for a year without asking again
(`immutable`); when the file changes, its hash and so its URL change, and the
browser fetches the new one. Without the hash (or with an old one) the file
must be revalidated every time (`no-cache` with ETag: a 304 costs one round
trip, but nobody ever sees a stale file). This keeps repeat visits fast, which
matters for Core Web Vitals (docs/framework.md, "Responsibilities").

A query string rather than a new file name: no build step and no manifest, the
files stay where they are. Fonts are not fingerprinted: a stylesheet refers to
them by plain relative URLs, so a fingerprinted preload link would download the
font a second time under another URL. They are cached for 30 days instead
(security and performance audit 2026-11-06: revalidating them cost every page
view one round trip per font before the text could be drawn in it). **A
replaced font must get a new file name**, or returning visitors keep the old
one for up to 30 days; 30 days rather than a year keeps that mistake short.

Python's mimetypes does not know web fonts on every system (Python 3.13 on
Windows, the slim Docker image), so the types are registered here; otherwise
fonts went out as application/octet-stream.
"""

import hashlib
import mimetypes
from pathlib import Path

from flask import Flask, current_app, request

ONE_YEAR = 365 * 24 * 3600
FONT_MAX_AGE = 30 * 24 * 3600
FONT_TYPES = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf"}
STATIC_ENDPOINTS = ("static", "evrima.static")
NOT_FINGERPRINTED = (".woff2", ".woff", ".ttf", ".otf")
_CACHE_KEY = "evrima.static_hashes"


def _folder(endpoint: str) -> Path | None:
    """The folder a static endpoint serves from."""
    if endpoint == "static":
        folder = current_app.static_folder
    else:
        blueprint = current_app.blueprints.get(endpoint.split(".", 1)[0])
        folder = blueprint.static_folder if blueprint else None
    return Path(folder) if folder else None


def fingerprint(endpoint: str, filename: str) -> str | None:
    """A short hash of the file's content, or None when the file is not there.

    Cached per process, except in development, where files change while the
    server runs and an outdated hash would serve an outdated file for a year.
    """
    cache = current_app.extensions.setdefault(_CACHE_KEY, {})
    key = (endpoint, filename)
    if key in cache and current_app.config.get("EVRIMA_ENV") != "development":
        return cache[key]
    folder = _folder(endpoint)
    path = (folder / filename).resolve() if folder else None
    value = None
    if path and folder and path.is_relative_to(folder.resolve()) and path.is_file():
        value = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    cache[key] = value
    return value


def _add_fingerprint(endpoint: str, values: dict) -> None:
    """url_defaults hook: add `v` to static URLs that do not have one."""
    if endpoint not in STATIC_ENDPOINTS or "v" in values:
        return
    filename = values.get("filename") or ""
    if filename.lower().endswith(NOT_FINGERPRINTED):
        return
    value = fingerprint(endpoint, filename)
    if value:
        values["v"] = value


def _cache_headers(response):
    """Long cache for a fingerprinted file whose hash matches, revalidation for the rest."""
    if request.endpoint in STATIC_ENDPOINTS and response.status_code in (200, 304):
        filename = (request.view_args or {}).get("filename", "")
        requested = request.args.get("v")
        if requested and requested == fingerprint(request.endpoint, filename):
            response.headers["Cache-Control"] = f"public, max-age={ONE_YEAR}, immutable"
        elif filename.lower().endswith(NOT_FINGERPRINTED):
            response.headers["Cache-Control"] = f"public, max-age={FONT_MAX_AGE}"
        else:
            response.headers["Cache-Control"] = "no-cache"
    return response


def init_app(app: Flask) -> None:
    """Fingerprint static URLs, set their cache headers and the web font types."""
    for extension, mimetype in FONT_TYPES.items():
        mimetypes.add_type(mimetype, extension)
    app.url_defaults(_add_fingerprint)
    app.after_request(_cache_headers)
