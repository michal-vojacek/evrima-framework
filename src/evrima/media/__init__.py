"""Uploaded files: images and documents for any module.

A module receives a file (usually already uploaded in the background by the
admin, see `views.upload`), keeps its `MediaFile.id` and calls `claim()` when
the form that uses it is saved:

    from evrima import media

    photo = media.save_upload(request.files["photo"], kinds=("image",))
    media.claim([photo.id])
    media.url(photo, width=960, fmt="webp")

Rules (docs/framework.md, "Uploads and the rich-text editor"):

- the type comes from the file's content, not its name: JPEG, PNG, WebP images
  and PDF documents only; SVG and HTML are refused because they can run
  scripts;
- images are decoded and saved again, which drops EXIF data (GPS position
  included) and anything appended to the file, and turns photos upright;
  WebP and AVIF variants are made for responsive images;
- files live on the local disk under MEDIA_ROOT and are served publicly from
  /media/ under random names.
"""

import io
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from flask import Flask, current_app, url_for
from PIL import Image, ImageOps
from sqlalchemy import select, update
from werkzeug.datastructures import FileStorage

from evrima.db import db, utcnow
from evrima.media.models import MediaFile

# Content signatures. The browser's content type and the file name can say
# anything; the first bytes cannot lie about the format a decoder will use.
SIGNATURES = (
    (b"\xff\xd8\xff", "image", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image", "png", "image/png"),
    (b"%PDF-", "document", "pdf", "application/pdf"),
)
KINDS = ("image", "document")
# Pillow decoder for each allowed image type (see _store_image).
PILLOW_FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}

DEFAULT_MAX_BYTES = {"image": 10 * 1024 * 1024, "document": 20 * 1024 * 1024}
MAX_SIDE = 2560
VARIANT_WIDTHS = (480, 960, 1600)
VARIANT_FORMATS = ("webp", "avif")
# A small file can unpack into a huge bitmap; anything above this is refused
# before decoding (about 160 MB of memory at most); common phone and camera
# photos stay well below it.
MAX_PIXELS = 40_000_000
UNCLAIMED_LIFETIME = timedelta(hours=24)


class UploadError(ValueError):
    """The upload was refused. `key` is the catalogue key of the reason for the user."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


@dataclass(frozen=True)
class Detected:
    """What the content of a file turned out to be."""

    kind: str
    extension: str
    content_type: str


def init_app(app: Flask) -> None:
    """Prepare the media folder and the image limits."""
    root = Path(app.config.get("MEDIA_ROOT") or Path(app.instance_path) / "media")
    root.mkdir(parents=True, exist_ok=True)
    app.config["MEDIA_ROOT"] = str(root)
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    # For website templates: <img src="{{ media_url(photo, 960) }}"
    # srcset="{{ media_srcset(photo) }}">.
    app.jinja_env.globals.update(media_url=url, media_srcset=srcset)


def media_root() -> Path:
    """The folder that holds every stored file of the current app."""
    return Path(current_app.config["MEDIA_ROOT"])


def detect(head: bytes) -> Detected | None:
    """Recognise a file from its first bytes; None for anything not allowed."""
    for signature, kind, extension, content_type in SIGNATURES:
        if head.startswith(signature):
            return Detected(kind, extension, content_type)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Detected("image", "webp", "image/webp")
    return None


def save_upload(
    upload: FileStorage,
    *,
    kinds: Iterable[str] = KINDS,
    max_bytes: int | None = None,
    uploaded_by: int | None = None,
) -> MediaFile:
    """Check, process and store one uploaded file. Raises UploadError with the reason."""
    kinds = tuple(kinds)
    data = upload.stream.read()
    detected = detect(data[:16])
    if detected is None or detected.kind not in kinds:
        raise UploadError("media.error.type")
    limit = max_bytes or DEFAULT_MAX_BYTES[detected.kind]
    if len(data) > limit:
        raise UploadError("media.error.size", max=_megabytes(limit))

    record = MediaFile(
        kind=detected.kind, stored_name=secrets.token_hex(16),
        extension=detected.extension, content_type=detected.content_type,
        original_name=Path(upload.filename or "").name[:255], size=len(data),
        uploaded_by=uploaded_by)
    if detected.kind == "image":
        _store_image(record, data)
    else:
        (media_root() / record.filename).write_bytes(data)
    db.session.add(record)
    db.session.commit()
    return record


def _store_image(record: MediaFile, data: bytes) -> None:
    """Decode, clean and save an image and its variants into the media folder."""
    try:
        # Only the decoder of the detected format: the signature check looked
        # at a few bytes, and Pillow would otherwise try every format it knows.
        with Image.open(io.BytesIO(data), formats=[PILLOW_FORMATS[record.extension]]) as source:
            # Opening reads only the header; refuse a huge bitmap before it is
            # unpacked into memory. (Pillow itself refuses only twice the limit.)
            if source.width * source.height > MAX_PIXELS:
                raise UploadError("media.error.too_many_pixels")
            source.load()
            image = ImageOps.exif_transpose(source)
    except UploadError:
        raise
    except Image.DecompressionBombError as error:
        raise UploadError("media.error.too_many_pixels") from error
    except (OSError, SyntaxError, ValueError) as error:
        raise UploadError("media.error.broken") from error

    image.thumbnail((MAX_SIDE, MAX_SIDE))
    # Keep transparency where the format has it (PNG, WebP); JPEG has none.
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha and record.extension != "jpg" else "RGB")

    root = media_root()
    # Saving without passing the original's info drops EXIF, ICC and comments.
    options = {"jpg": {"format": "JPEG", "quality": 88, "optimize": True},
               "png": {"format": "PNG", "optimize": True},
               "webp": {"format": "WEBP", "quality": 85}}[record.extension]
    target = root / record.filename
    image.save(target, **options)
    record.size = target.stat().st_size
    record.width, record.height = image.size

    # Never enlarged: a smaller image gets the widths below its own, plus a
    # variant at its full width, so the largest variant always shows it whole.
    widths = [width for width in VARIANT_WIDTHS if width < image.width]
    if image.width <= max(VARIANT_WIDTHS):
        widths.append(image.width)
    for width in widths:
        variant = image.copy()
        variant.thumbnail((width, MAX_SIDE))
        for fmt in VARIANT_FORMATS:
            variant.save(root / f"{record.stored_name}-{width}.{fmt}", format=fmt.upper(), quality=80)
    record.variants = ",".join(str(width) for width in widths)


def _megabytes(limit: int) -> str:
    """A byte limit as whole megabytes for messages."""
    return f"{limit // (1024 * 1024)} MB"


def url(record: MediaFile, width: int | None = None, fmt: str | None = None) -> str:
    """Public URL of the file, or of an image variant (`width` and `fmt` "webp"/"avif")."""
    if width and record.kind == "image":
        width = min((w for w in record.variant_widths if w >= width), default=max(record.variant_widths))
        return url_for("evrima_media.serve", name=f"{record.stored_name}-{width}.{fmt or 'webp'}")
    return url_for("evrima_media.serve", name=record.filename)


def srcset(record: MediaFile, fmt: str = "webp") -> str:
    """A srcset value with every variant of an image in `fmt`."""
    return ", ".join(
        f"{url_for('evrima_media.serve', name=f'{record.stored_name}-{w}.{fmt}')} {w}w"
        for w in record.variant_widths)


def take(file_id: int | None, *, kinds: Iterable[str] = KINDS) -> MediaFile | None:
    """Claim one freshly uploaded file for a record that is being saved.

    Returns the file, or None when `file_id` is not a file of `kinds` that
    nobody has claimed yet. The id comes from the browser: without this check
    a crafted id could attach another module's file, which the record would
    later delete together with itself. The claim is a single conditional
    UPDATE, so two forms saved at once cannot both take the same file.

    Nothing is committed: the caller commits the claim together with its own
    record, so a crash in between leaves neither (an unclaimed file is then
    removed by the cleanup, as if the form was never sent).
    """
    if file_id is None:
        return None
    result = db.session.execute(
        update(MediaFile)
        .where(MediaFile.id == file_id, MediaFile.claimed_at.is_(None), MediaFile.kind.in_(tuple(kinds)))
        .values(claimed_at=utcnow()))
    return db.session.get(MediaFile, file_id) if result.rowcount == 1 else None


def claim(ids: Iterable[int]) -> list[MediaFile]:
    """Mark files as used by a saved form, so the cleanup keeps them. Returns them.

    For a single file chosen in a form, prefer `take`, which also refuses
    files that are already used or of the wrong kind.
    """
    ids = [int(i) for i in ids]
    if not ids:
        return []
    db.session.execute(
        update(MediaFile).where(MediaFile.id.in_(ids), MediaFile.claimed_at.is_(None))
        .values(claimed_at=utcnow()))
    db.session.commit()
    return list(db.session.scalars(select(MediaFile).where(MediaFile.id.in_(ids))))


def delete(record: MediaFile) -> None:
    """Remove a file, its variants and its record."""
    root = media_root()
    for path in root.glob(f"{record.stored_name}*"):
        path.unlink(missing_ok=True)
    db.session.delete(record)
    db.session.commit()


def cleanup(older_than: timedelta = UNCLAIMED_LIFETIME) -> int:
    """Delete files that were uploaded but never claimed. Returns how many."""
    cutoff = utcnow() - older_than
    stale = db.session.scalars(select(MediaFile).where(
        MediaFile.claimed_at.is_(None), MediaFile.created_at < cutoff)).all()
    for record in stale:
        delete(record)
    return len(stale)
