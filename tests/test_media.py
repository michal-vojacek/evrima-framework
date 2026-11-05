"""Uploaded files: type checks, image cleaning, serving and the admin upload endpoint."""

import io
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from conftest import csrf_token
from evrima import media
from evrima.db import db
from evrima.media.models import MediaFile

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def image_bytes(fmt="JPEG", size=(1200, 800), mode="RGB", exif=None):
    """A generated image file of the given format."""
    buffer = io.BytesIO()
    options = {"exif": exif} if exif is not None else {}
    Image.new(mode, size, "teal" if mode != "RGBA" else (0, 128, 128, 100)).save(buffer, fmt, **options)
    return buffer.getvalue()


def as_upload(data, filename):
    """Bytes wrapped like a file from a form."""
    return FileStorage(stream=io.BytesIO(data), filename=filename)


@pytest.mark.parametrize(("data", "expected"), [
    (image_bytes("JPEG"), ("image", "jpg")),
    (image_bytes("PNG"), ("image", "png")),
    (image_bytes("WEBP"), ("image", "webp")),
    (PDF, ("document", "pdf")),
], ids=["jpeg", "png", "webp", "pdf"])
def test_allowed_types_are_recognised_by_content(data, expected):
    detected = media.detect(data[:16])
    assert (detected.kind, detected.extension) == expected


@pytest.mark.parametrize("data", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b"<!doctype html><script>alert(1)</script>",
    image_bytes("GIF"),
    b"",
], ids=["svg", "html", "gif", "empty"])
def test_other_types_are_not_recognised(data):
    assert media.detect(data[:16]) is None


def test_a_photo_is_stored_upright_without_exif_and_with_variants(app):
    exif = Image.Exif()
    exif[0x0112] = 6                     # orientation: rotated 90 degrees
    exif[0x010E] = "Secret description"  # stands in for GPS and camera data
    with app.app_context():
        record = media.save_upload(as_upload(image_bytes(exif=exif), "Holiday.JPG"))
        root = media.media_root()
        with Image.open(root / record.filename) as stored:
            assert stored.size == (800, 1200)          # turned upright
            assert not stored.getexif()
            assert b"Secret" not in (root / record.filename).read_bytes()
        assert (record.kind, record.extension, record.original_name) == ("image", "jpg", "Holiday.JPG")
        assert (record.width, record.height) == (800, 1200)
        assert record.variant_widths == [480, 800]
        for width in record.variant_widths:
            for fmt in ("webp", "avif"):
                with Image.open(root / f"{record.stored_name}-{width}.{fmt}") as variant:
                    assert variant.width == width
        assert record.claimed_at is None


def test_large_images_are_scaled_down(app):
    with app.app_context():
        record = media.save_upload(as_upload(image_bytes("PNG", size=(4000, 1000)), "wide.png"))
    assert (record.width, record.height) == (2560, 640)
    assert record.variant_widths == [480, 960, 1600]


def test_transparency_is_kept_in_png(app):
    with app.app_context():
        record = media.save_upload(as_upload(image_bytes("PNG", mode="RGBA"), "logo.png"))
        with Image.open(media.media_root() / record.filename) as stored:
            assert stored.mode == "RGBA"


def test_pdf_is_stored_unchanged(app):
    with app.app_context():
        record = media.save_upload(as_upload(PDF, "Price list.pdf"), kinds=("document",))
        assert (media.media_root() / record.filename).read_bytes() == PDF
    assert (record.kind, record.content_type, record.variant_widths) == ("document", "application/pdf", [])


@pytest.mark.parametrize(("data", "filename", "kinds", "key"), [
    (b"<!doctype html><script>alert(1)</script>", "photo.jpg", media.KINDS, "media.error.type"),
    (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "logo.svg", media.KINDS, "media.error.type"),
    (PDF, "document.pdf", ("image",), "media.error.type"),
    (image_bytes("JPEG"), "photo.jpg", ("document",), "media.error.type"),
    (b"\xff\xd8\xff" + b"not really a jpeg" * 10, "broken.jpg", media.KINDS, "media.error.broken"),
], ids=["html-named-jpg", "svg", "pdf-in-image-field", "image-in-document-field", "broken-jpeg"])
def test_refused_uploads_leave_nothing_behind(app, data, filename, kinds, key):
    with app.app_context():
        with pytest.raises(media.UploadError) as refused:
            media.save_upload(as_upload(data, filename), kinds=kinds)
        assert refused.value.key == key
        assert db.session.query(MediaFile).count() == 0
        assert list(media.media_root().iterdir()) == []


def test_size_limit(app):
    with app.app_context():
        with pytest.raises(media.UploadError) as refused:
            media.save_upload(as_upload(PDF, "big.pdf"), max_bytes=10)
    assert refused.value.key == "media.error.size"


def test_images_with_too_many_pixels_are_refused_before_decoding(app, monkeypatch):
    monkeypatch.setattr(media, "MAX_PIXELS", 100 * 100)
    with app.app_context():
        with pytest.raises(media.UploadError) as refused:
            media.save_upload(as_upload(image_bytes("PNG", size=(101, 100)), "huge.png"))
    assert refused.value.key == "media.error.too_many_pixels"


def test_urls_pick_the_nearest_larger_variant(app):
    with app.test_request_context():
        record = media.save_upload(as_upload(image_bytes(size=(2000, 1000)), "photo.jpg"))
        name = record.stored_name
        assert media.url(record) == f"/media/{name}.jpg"
        assert media.url(record, width=500) == f"/media/{name}-960.webp"
        assert media.url(record, width=5000, fmt="avif") == f"/media/{name}-1600.avif"
        assert media.srcset(record, "avif") == (
            f"/media/{name}-480.avif 480w, /media/{name}-960.avif 960w, /media/{name}-1600.avif 1600w")


def test_files_are_served_with_long_caching(app, client):
    with app.app_context():
        record = media.save_upload(as_upload(image_bytes(), "photo.jpg"))
        name, stored_name = record.filename, record.stored_name
    response = client.get(f"/media/{name}")
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert "immutable" in response.headers["Cache-Control"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get(f"/media/{stored_name}-480.avif").mimetype == "image/avif"
    assert client.get("/media/missing.jpg").status_code == 404
    assert client.get("/media/..%2Fsecret.txt").status_code == 404


def test_pdf_is_served_sandboxed_under_its_original_name(app, client):
    with app.app_context():
        record = media.save_upload(as_upload(PDF, "Price list 2026.pdf"), kinds=("document",))
        name = record.filename
    response = client.get(f"/media/{name}")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Security-Policy"] == media.views.DOCUMENT_CSP
    disposition = response.headers["Content-Disposition"]
    assert disposition == 'inline; filename="Price list 2026.pdf"'


def test_claim_and_cleanup(app):
    with app.app_context():
        kept = media.save_upload(as_upload(image_bytes(), "kept.jpg"))
        dropped = media.save_upload(as_upload(PDF, "dropped.pdf"))
        fresh = media.save_upload(as_upload(PDF, "fresh.pdf"))
        media.claim([kept.id])
        for record in (kept, dropped):
            record.created_at -= timedelta(days=2)
        db.session.commit()

        assert media.cleanup() == 1
        names = {path.name for path in media.media_root().iterdir()}
        assert kept.filename in names and fresh.filename in names
        assert not any(name.startswith(dropped.stored_name) for name in names)
        assert db.session.get(MediaFile, kept.id).claimed_at is not None


def test_cleanup_command(app):
    with app.app_context():
        record = media.save_upload(as_upload(PDF, "old.pdf"))
        record.created_at -= timedelta(days=2)
        db.session.commit()
    result = app.test_cli_runner().invoke(args=["evrima", "media", "cleanup"])
    assert result.exit_code == 0
    assert "Removed 1 unused file(s)." in result.output


def upload(client, data, filename, kinds="image", token=None):
    """POST one file to the admin's upload endpoint like admin.js does."""
    headers = {"X-CSRFToken": token} if token else {}
    return client.post("/admin/media/upload", headers=headers, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data), filename), "kinds": kinds})


def test_upload_endpoint_requires_login(app, client):
    response = upload(client, image_bytes(), "photo.jpg", token=csrf_token(client))
    assert response.status_code == 302
    with app.app_context():
        assert db.session.query(MediaFile).count() == 0


def test_upload_endpoint_requires_the_csrf_token(admin_client):
    assert upload(admin_client, image_bytes(), "photo.jpg").status_code == 400


def test_upload_endpoint_stores_and_describes_the_file(app, admin_client):
    token = csrf_token(admin_client, "/admin/design")
    response = upload(admin_client, image_bytes(), "photo.jpg", token=token)
    assert response.status_code == 200
    file = response.get_json()["file"]
    assert file["name"] == "photo.jpg" and file["kind"] == "image"
    assert file["url"].endswith(".jpg") and file["preview"].endswith("-480.webp")
    with app.app_context():
        record = db.session.get(MediaFile, file["id"])
        assert record.uploaded_by is not None
        assert Path(app.config["MEDIA_ROOT"], record.filename).exists()


def test_upload_endpoint_explains_a_refusal_in_the_admin_language(admin_client):
    token = csrf_token(admin_client, "/admin/design")
    response = upload(admin_client, PDF, "document.pdf", kinds="image", token=token)
    assert response.status_code == 422
    body = response.get_json()
    assert body["ok"] is False
    assert body["message"].startswith("Tento typ souboru")

    response = upload(admin_client, PDF, "document.pdf", kinds="document", token=token)
    assert response.status_code == 200
    assert response.get_json()["file"]["preview"] is None


def test_take_claims_only_fresh_files_of_the_right_kind(app):
    """The id of a file chosen in a form comes from the browser and cannot be trusted."""
    with app.app_context():
        photo = media.save_upload(as_upload(image_bytes(), "photo.jpg"))
        document = media.save_upload(as_upload(PDF, "doc.pdf"))
        assert media.take(document.id, kinds=("image",)) is None
        assert media.take(424242) is None
        assert media.take(None) is None
        assert media.take(photo.id, kinds=("image",)).id == photo.id
        db.session.commit()
        # Already used: a second form cannot take it.
        assert media.take(photo.id) is None


def test_images_are_decoded_only_as_their_detected_format(app):
    """A PNG signature in front of another format is refused, not decoded by another decoder."""
    fake = b"\x89PNG\r\n\x1a\n" + image_bytes("GIF")[8:]
    with app.app_context(), pytest.raises(media.UploadError):
        media.save_upload(as_upload(fake, "fake.png"))
