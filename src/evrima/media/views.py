"""Serving stored files and the admin's background upload endpoint."""

from flask import Blueprint, abort, current_app, jsonify, request, send_from_directory
from sqlalchemy import select

from evrima import media, security
from evrima.config import DEFAULT_MAX_CONTENT_LENGTH
from evrima.auth import protect
from evrima.auth.sessions import current_admin
from evrima.db import db
from evrima.i18n import translate as t
from evrima.media.models import MediaFile

# Public: /media/<name>. Names are random, so a URL cannot be guessed, and
# every response is immutable: a changed file always gets a new name.
public = Blueprint("evrima_media", __name__)

# Admin: the upload endpoint behind the login.
admin = Blueprint("evrima_media_admin", __name__, url_prefix="/admin/media")
protect(admin)

ONE_YEAR = 365 * 24 * 3600
# A stored PDF is shown by the browser's own viewer; with its fixed content
# type and nosniff it is never run as a web page. The website's policy would
# forbid framing (frame-ancestors 'none') and so stop the site's own pages
# from showing a document in a frame; this one allows that and nothing else.
# No `sandbox`: it protects nothing here, and a viewer might refuse to run in
# a sandboxed document. (Checked 2026-10-15: Chrome starts its viewer under
# this policy just as without any.)
DOCUMENT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'self'"


@public.get("/media/<name>")
def serve(name: str):
    """Send a stored file or image variant with long-lived caching."""
    download_name = None
    if name.endswith(".pdf"):
        # A visitor who saves the document gets its original name
        # ("Price list 2026.pdf"), not the random one.
        stored_name = name.removesuffix(".pdf")
        record = db.session.scalar(select(MediaFile).where(MediaFile.stored_name == stored_name))
        if record is None:
            abort(404)
        download_name = record.original_name or None
    response = send_from_directory(
        current_app.config["MEDIA_ROOT"], name, max_age=ONE_YEAR, conditional=True,
        download_name=download_name)
    response.headers["Cache-Control"] = f"public, max-age={ONE_YEAR}, immutable"
    if name.endswith(".pdf"):
        response.headers["Content-Security-Policy"] = DOCUMENT_CSP
    return response


@admin.post("/upload")
@security.body_limit(DEFAULT_MAX_CONTENT_LENGTH)       # one file, up to the largest allowed document
def upload():
    """Store one file sent by the admin's upload field; answer with JSON.

    The admin uploads each chosen file at once, with a progress bar, and the
    form later submits only the ids it got back. `kinds` limits the accepted
    types to what the field asked for (image, document).
    """
    file = request.files.get("file")
    if file is None:
        abort(400)
    kinds = [k for k in request.form.get("kinds", "image").split(",") if k in media.KINDS] or ["image"]
    try:
        record = media.save_upload(file, kinds=kinds, uploaded_by=current_admin().id)
    except media.UploadError as error:
        return jsonify(ok=False, message=t(error.key, **error.params)), 422
    return jsonify(ok=True, file=describe(record))


def describe(record: MediaFile) -> dict:
    """What the admin's script needs to show an uploaded file."""
    preview = media.url(record, width=480) if record.kind == "image" else None
    return {"id": record.id, "name": record.original_name, "size": record.size,
            "kind": record.kind, "url": media.url(record), "preview": preview}
