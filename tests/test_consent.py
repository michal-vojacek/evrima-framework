"""Consent banner: the visitor's choice per category, the banner, the settings page, the helpers."""

import pytest
from flask import Blueprint, render_template_string

from conftest import https_client
from evrima import consent
from evrima.config import ConfigError

ON = {"CONSENT_CATEGORIES": ["analytics", "marketing"]}
SHOWN = 'aria-labelledby="evrima-consent-title">'
HIDDEN = 'aria-labelledby="evrima-consent-title" hidden>'

pages = Blueprint("consent_pages", __name__)


@pages.get("/page")
def page():
    return render_template_string(
        '{% extends "base.html" %}{% block content %}'
        '{% if consent("analytics") %}ANALYTICS{% endif %}{% if consent("marketing") %}MARKETING{% endif %}'
        '{% endblock %}')


def browser(app):
    """A client sending what a browser sends from the website's own page."""
    client = https_client(app)
    client.environ_base["HTTP_SEC_FETCH_SITE"] = "same-origin"
    return client


@pytest.fixture
def on_app(make_app):
    return make_app(blueprints=[pages], **ON)


def test_off_by_default(make_app):
    client = browser(make_app(blueprints=[pages]))
    body = client.get("/page").get_data(as_text=True)
    assert "evrima-consent" not in body and "consent.js" not in body
    assert client.get("/_evrima/consent").status_code == 404
    assert client.post("/_evrima/consent", data={"choice": "all"}).status_code == 404


def test_the_banner_shows_until_the_visitor_decides(on_app):
    client = browser(on_app)
    body = client.get("/page").get_data(as_text=True)
    assert SHOWN in body
    assert "consent.js" in body and "consent.css" in body
    assert "Odmítnout vše" in body and "Přijmout vše" in body
    assert "ANALYTICS" not in body

    client.post("/_evrima/consent", data={"choice": "none", "next": "/page"})
    assert HIDDEN in client.get("/page").get_data(as_text=True)


@pytest.mark.parametrize("data, allowed", [
    ({"choice": "all"}, {"analytics", "marketing"}),
    ({"choice": "none", "category": "analytics"}, set()),
    ({"choice": "selected", "category": ["analytics", "unknown"]}, {"analytics"}),
    ({"choice": "selected"}, set()),
])
def test_the_choice_is_stored_per_category(on_app, data, allowed):
    client = browser(on_app)
    response = client.post("/_evrima/consent", data={**data, "next": "/page"})
    assert response.status_code == 303 and response.location == "/page"
    body = client.get("/page").get_data(as_text=True)
    assert ("ANALYTICS" in body) == ("analytics" in allowed)
    assert ("MARKETING" in body) == ("marketing" in allowed)


def test_the_cookie(on_app):
    response = browser(on_app).post("/_evrima/consent", data={"choice": "selected", "category": "marketing"})
    header = response.headers["Set-Cookie"]
    assert header.startswith("evrima_consent=v1.marketing;")
    assert "Max-Age=31536000" in header and "Secure" in header and "SameSite=Lax" in header
    assert "HttpOnly" not in header         # the page's script reads it


def test_the_script_gets_json(on_app):
    response = browser(on_app).post(
        "/_evrima/consent", data={"choice": "all"}, headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.get_json() == {"categories": ["analytics", "marketing"]}


def test_a_new_consent_version_asks_again(make_app):
    client = browser(make_app(blueprints=[pages], **ON))
    client.post("/_evrima/consent", data={"choice": "all"})
    cookie = client.get_cookie("evrima_consent").value

    client = browser(make_app(blueprints=[pages], CONSENT_VERSION=2, **ON))
    client.set_cookie("evrima_consent", cookie)
    body = client.get("/page").get_data(as_text=True)
    assert "ANALYTICS" not in body and SHOWN in body


def test_a_tampered_cookie_grants_only_known_categories(on_app):
    with on_app.test_request_context(headers={"Cookie": "evrima_consent=v1.analytics.everything"}):
        assert consent.choice() == frozenset({"analytics"})
        assert consent.given("analytics") and not consent.given("everything")


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://attacker.example"},
    {},
])
def test_other_websites_cannot_set_the_choice(on_app, headers):
    client = https_client(on_app)
    response = client.post("/_evrima/consent", data={"choice": "all"}, headers=headers)
    assert response.status_code == 403
    assert client.get_cookie("evrima_consent") is None


def test_no_session_cookie_just_for_the_banner(on_app):
    client = browser(on_app)
    client.get("/page")
    assert client.post("/_evrima/consent", data={"choice": "none"}).status_code == 303
    assert client.get_cookie("session") is None


@pytest.mark.parametrize("target", ["https://attacker.example/", "//attacker.example/", "/\\attacker.example"])
def test_the_return_address_stays_on_the_website(on_app, target):
    response = browser(on_app).post("/_evrima/consent", data={"choice": "none", "next": target})
    assert response.location == "/"


def test_an_unknown_choice_is_refused(on_app):
    assert browser(on_app).post("/_evrima/consent", data={"choice": "maybe"}).status_code == 400


def test_the_settings_page(on_app):
    client = browser(on_app)
    client.post("/_evrima/consent", data={"choice": "selected", "category": "analytics"})
    body = client.get("/_evrima/consent?next=/page").get_data(as_text=True)
    assert "<h1>Nastavení cookies</h1>" in body
    assert '<details class="evrima-consent__details" open>' in body
    assert 'value="analytics" checked>' in body and 'value="marketing">' in body
    assert 'name="next" value="/page"' in body
    assert SHOWN not in body and HIDDEN not in body          # no second form in a banner


def test_the_footer_link_and_english_texts(make_app):
    body = browser(make_app(blueprints=[pages], SITE_LANGUAGE="en", **ON)).get("/page").get_data(as_text=True)
    assert 'href="/_evrima/consent" data-evrima-consent-open>Cookie settings</a>' in body
    assert "Reject all" in body and "Accept all" in body


def test_a_category_needs_its_texts(make_app):
    with pytest.raises(ConfigError, match="consent.category.social.name"):
        make_app(CONSENT_CATEGORIES=["social"])


def test_a_website_category_with_its_own_texts(make_app, tmp_path, monkeypatch):
    from evrima import i18n

    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "social.toml").write_text(
        '[consent.category.social.name]\nen = "Social"\ncs = "Sociální sítě"\n'
        '[consent.category.social.description]\nen = "Embedded posts."\ncs = "Vložené příspěvky."\n',
        encoding="utf-8")
    original = i18n.Catalogue.load_directory

    def with_website_texts(self, directory):
        original(self, directory)
        if directory == i18n.FRAMEWORK_CATALOGUE:
            original(self, texts)
    monkeypatch.setattr(i18n.Catalogue, "load_directory", with_website_texts)
    app = make_app(blueprints=[pages], CONSENT_CATEGORIES=["social"])
    assert "Sociální sítě" in browser(app).get("/page").get_data(as_text=True)


@pytest.mark.parametrize("overrides, message", [
    ({"CONSENT_CATEGORIES": ["necessary"]}, "need no consent"),
    ({"CONSENT_CATEGORIES": ["Analytics"]}, "lower-case"),
    ({"CONSENT_CATEGORIES": ["analytics", "analytics"]}, "twice"),
    ({"CONSENT_CATEGORIES": "analytics"}, "must be a list"),
    ({"CONSENT_VERSION": 0}, "CONSENT_VERSION"),
    ({"SITE_LANGUAGE": "de"}, "SITE_LANGUAGE"),
])
def test_invalid_settings_are_refused(make_app, overrides, message):
    with pytest.raises(ConfigError, match=message):
        make_app(**overrides)
