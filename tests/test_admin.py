"""Admin frame: the design cookbook, the language switch and CSP-safe markup."""

import re

import pytest

from conftest import csrf_token


@pytest.fixture
def page(admin_client):
    """The design page in the default language (Czech), as a logged-in administrator."""
    response = admin_client.get("/admin/design")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_design_page_renders_in_czech_by_default(page):
    assert '<html lang="cs">' in page
    assert "Design systém" in page
    assert "Krátké formuláře: dialog" in page


def test_admin_pages_require_login(client):
    for path in ("/admin/", "/admin/design", "/admin/account", "/admin/administrators"):
        response = client.get(path)
        assert response.status_code == 302, path
        assert "/admin/login?next=" in response.headers["Location"], path


def test_language_switch_changes_texts_and_returns(admin_client):
    response = admin_client.post("/admin/language", data={
        "csrf_token": csrf_token(admin_client, "/admin/design"), "language": "en",
        "next": "/admin/design#languages"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/design#languages"
    english = admin_client.get("/admin/design").get_data(as_text=True)
    assert '<html lang="en">' in english
    assert "Short forms: dialog" in english
    assert "The admin is now in English." in english


def test_language_switch_works_before_login(client):
    response = client.post("/admin/language", data={
        "csrf_token": csrf_token(client), "language": "en", "next": "/admin/login"})
    assert response.headers["Location"] == "/admin/login"
    assert "Log in" in client.get("/admin/login").get_data(as_text=True)


def test_language_switch_refuses_external_redirects(client):
    token = csrf_token(client)
    for target in ("https://evil.example.com/", "//evil.example.com/", "/\\evil.example.com"):
        response = client.post("/admin/language", data={
            "csrf_token": token, "language": "en", "next": target})
        assert response.headers["Location"] == "/admin/"


def test_language_switch_rejects_unknown_language(client):
    response = client.post("/admin/language", data={
        "csrf_token": csrf_token(client), "language": "de", "next": "/admin/"})
    assert response.status_code == 400


def test_language_switch_requires_csrf_token(client):
    response = client.post("/admin/language", data={"language": "en"})
    assert response.status_code == 400


def test_mobile_menu_button_is_accessible(page):
    # The phone menu is a disclosure: the button names its action, says
    # whether the panel is open, and points at the panel it controls.
    button = re.search(r"<button[^>]*data-nav-toggle[^>]*>", page).group(0)
    assert 'aria-expanded="false"' in button
    assert 'aria-controls="sidebar-panel"' in button
    assert 'aria-label="Otevřít menu"' in button
    assert 'id="sidebar-panel"' in page


def test_plural_forms_render(page):
    assert "1 fotka" in page and "2 fotky" in page and "5 fotek" in page


def test_script_texts_are_handed_over_in_the_page_language(page):
    match = re.search(r'data-i18n="([^"]+)"', page)
    assert match
    assert "Zkopírováno" in match.group(1) or "Zkop\\u00edrov\\u00e1no" in match.group(1)


@pytest.mark.parametrize("path", [
    "/admin/", "/admin/design", "/admin/account", "/admin/administrators"])
def test_admin_markup_has_nothing_inline(admin_client, path):
    # The CSP forbids inline scripts, inline styles and inline handlers; one
    # slip in a template would be blocked by the browser and break the page.
    html = admin_client.get(path).get_data(as_text=True)
    assert not re.search(r"\sstyle\s*=", html), path
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), path
    assert not re.search(r"\son[a-z]+\s*=", html), path
    assert not re.search(r">\s*(admin|auth)\.[a-z_.]+\s*<", html), path


def test_login_pages_have_nothing_inline(client):
    for path in ("/admin/login", "/admin/password/forgot"):
        html = client.get(path).get_data(as_text=True)
        assert not re.search(r"\sstyle\s*=", html), path
        assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), path


def test_admin_assets_are_served(client):
    for path in ("css/admin.css", "js/admin.js", "vendor/jquery/jquery.min.js",
                 "vendor/datatables/js/jquery.dataTables.min.js",
                 "vendor/fontawesome/css/all.min.css",
                 "vendor/fontawesome/webfonts/fa-brands-400.woff2"):
        response = client.get(f"/_evrima/static/{path}")
        assert response.status_code == 200, path
        response.close()


def test_admin_allows_blob_previews_but_public_pages_do_not(admin_client):
    admin_csp = admin_client.get("/admin/design").headers["Content-Security-Policy"]
    public_csp = admin_client.get("/health").headers["Content-Security-Policy"]
    assert "img-src 'self' blob:" in admin_csp
    assert "blob:" not in public_csp


def test_design_page_ids_are_unique(page):
    ids = re.findall(r'\sid="([^"]+)"', page)
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


def test_design_page_shows_the_new_components(page):
    for marker in ("data-upload", "data-sortable", "data-counter", 'class="breadcrumbs"',
                   'class="pagination"', 'class="disclosure', "is-busy"):
        assert marker in page, marker
