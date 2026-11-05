"""The minimal example website works end to end."""

import pytest

from conftest import BASE_ENV, https_client


@pytest.fixture
def site(monkeypatch):
    """The example website, configured through environment variables like a real one."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)
    from minimal_site import create_app
    return create_app()


def test_home_page(site):
    response = https_client(site).get("/")
    assert response.status_code == 200
    assert "Minimal Evrima website" in response.get_data(as_text=True)
    assert "Content-Security-Policy" in response.headers


def test_website_static_files_are_served(site):
    response = https_client(site).get("/static/site.css")
    assert response.status_code == 200
    response.close()


def test_framework_routes_are_present(site):
    assert https_client(site).get("/health").status_code == 200
