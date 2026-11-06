"""Default error pages and website overrides."""

from flask import Blueprint

from conftest import https_client

broken = Blueprint("broken", __name__)


@broken.get("/broken")
def broken_page():
    """Fail the way an unexpected bug would."""
    raise RuntimeError("database password is hunter2")


def test_website_overrides_its_404_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Fixture site 404" in response.get_data(as_text=True)


def test_framework_fallback_is_in_the_websites_language(client, make_app):
    response = client.post("/health")
    assert response.status_code == 405
    body = response.get_data(as_text=True)
    assert '<html lang="cs">' in body and "405 Nepovolená metoda" in body

    english = https_client(make_app(SITE_LANGUAGE="en")).post("/health")
    assert "405 Method Not Allowed" in english.get_data(as_text=True)


def test_unhandled_exception_renders_500_without_details(make_app):
    client = https_client(make_app(blueprints=[broken], SITE_LANGUAGE="en"))
    response = client.get("/broken")
    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert "500 Internal Server Error" in body
    assert "hunter2" not in body


def test_error_pages_carry_security_headers(client):
    assert "Content-Security-Policy" in client.get("/no-such-page").headers
