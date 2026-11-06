"""Static files: fingerprinted URLs and cache headers."""

import re

from flask import url_for

from conftest import https_client
from evrima import static_files


def test_static_urls_carry_the_hash_of_the_content(app):
    with app.test_request_context():
        url = url_for("evrima.static", filename="js/admin.js")
        assert re.fullmatch(r"/_evrima/static/js/admin\.js\?v=[0-9a-f]{12}", url)
        assert url_for("evrima.static", filename="js/admin.js") == url


def test_fonts_and_missing_files_are_not_fingerprinted(app):
    with app.test_request_context():
        assert "?v=" not in url_for("evrima.static", filename="vendor/fontawesome/webfonts/fa-solid-900.woff2")
        assert "?v=" not in url_for("evrima.static", filename="js/missing.js")


def test_a_path_outside_the_folder_gets_no_hash(app):
    with app.test_request_context():
        assert static_files.fingerprint("evrima.static", "../../config.py") is None


def test_a_matching_hash_is_cached_for_a_year(app):
    client = https_client(app)
    with app.test_request_context():
        url = url_for("evrima.static", filename="js/admin.js")
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_without_the_hash_or_with_an_old_one_the_file_is_revalidated(app):
    client = https_client(app)
    for url in ("/_evrima/static/js/admin.js", "/_evrima/static/js/admin.js?v=000000000000"):
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers.get("ETag")


def test_the_hash_follows_the_content_in_development(make_app, tmp_path, monkeypatch):
    app = make_app(env={"EVRIMA_ENV": "development"})
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / "site.css").write_text("a{}")
    monkeypatch.setattr(app, "static_folder", str(folder))
    with app.test_request_context():
        first = static_files.fingerprint("static", "site.css")
        (folder / "site.css").write_text("b{}")
        assert static_files.fingerprint("static", "site.css") != first


def test_fonts_are_cached_for_30_days_with_their_type(app):
    from evrima import static_files

    response = https_client(app).get("/_evrima/static/vendor/fontawesome/webfonts/fa-solid-900.woff2")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == f"public, max-age={static_files.FONT_MAX_AGE}"
    assert response.mimetype == "font/woff2"
