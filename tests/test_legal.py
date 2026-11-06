"""Skeletons of the legal pages: addresses, the framework's own cookies, website overrides."""

import pytest
from flask import render_template_string

from conftest import https_client
from evrima.config import ConfigError

TELEMETRY = {"TELEMETRY_ENDPOINT": "https://collector.example.com", "TELEMETRY_TOKEN": "site-token"}


def test_off_by_default(client):
    assert client.get("/zasady-ochrany-osobnich-udaju").status_code == 404
    assert client.get("/cookies").status_code == 404


def test_default_addresses_follow_the_websites_language(make_app):
    czech = https_client(make_app(LEGAL_PAGES=["privacy", "cookies"]))
    assert czech.get("/zasady-ochrany-osobnich-udaju").status_code == 200
    assert czech.get("/cookies").status_code == 200

    english = https_client(make_app(SITE_LANGUAGE="en", LEGAL_PAGES=["privacy"]))
    body = english.get("/privacy").get_data(as_text=True)
    assert "<h1>Privacy policy</h1>" in body and '<html lang="en">' in body
    assert english.get("/cookies").status_code == 404


def test_own_addresses_and_legal_url(make_app):
    app = make_app(LEGAL_PAGES={"privacy": "/ochrana-udaju"})
    assert https_client(app).get("/ochrana-udaju").status_code == 200
    with app.test_request_context():
        assert render_template_string('{{ legal_url("privacy") }}|{{ legal_url("cookies") }}') == "/ochrana-udaju|None"


def test_the_skeleton_marks_what_the_website_must_fill_in(make_app):
    body = https_client(make_app(LEGAL_PAGES=["privacy"])).get("/zasady-ochrany-osobnich-udaju").get_data(as_text=True)
    assert "<title>Zásady ochrany osobních údajů</title>" in body      # the website's layout, its title block
    assert body.count('class="evrima-legal-todo"') == 5
    assert "Vaše práva" in body
    assert "Statistiky návštěvnosti" not in body                       # telemetry is off
    assert "Cookies</a>" not in body                                   # no cookies page


def test_the_privacy_policy_mentions_what_the_framework_does(make_app):
    app = make_app(env=TELEMETRY, LEGAL_PAGES=["privacy", "cookies"],
                   CONSENT_CATEGORIES=["analytics"], TELEMETRY_VISITORS="analytics")
    body = https_client(app).get("/zasady-ochrany-osobnich-udaju").get_data(as_text=True)
    assert "Statistiky návštěvnosti" in body and "náhodný identifikátor" in body
    assert '<a href="/cookies">Cookies</a>' in body


def test_the_cookies_page_lists_the_frameworks_cookies(make_app):
    body = https_client(make_app(LEGAL_PAGES=["cookies"])).get("/cookies").get_data(as_text=True)
    assert "<code>session</code>" in body and "<code>evrima_admin</code>" in body
    assert "evrima_consent" not in body and "evrima_vid" not in body

    app = make_app(env=TELEMETRY, LEGAL_PAGES=["cookies"],
                   CONSENT_CATEGORIES=["analytics", "marketing"], TELEMETRY_VISITORS="analytics")
    body = https_client(app).get("/cookies").get_data(as_text=True)
    assert "<code>evrima_consent</code>" in body and "<code>evrima_vid</code>" in body
    assert "<h2>Analytické</h2>" in body and "<h2>Marketingové</h2>" in body
    assert 'data-evrima-consent-open>Nastavení cookies</a>' in body
    analytics, marketing = body.split("<h2>Analytické</h2>")[1].split("<h2>Marketingové</h2>")
    assert "evrima_vid" in analytics and "evrima_vid" not in marketing


def test_a_website_fills_the_blocks(make_app, tmp_path, monkeypatch):
    templates = tmp_path / "templates" / "legal"
    templates.mkdir(parents=True)
    (templates / "cookies.html").write_text(
        '{% extends "evrima/legal/cookies.cs.html" %}'
        '{% from "evrima/legal/_macros.html" import cookie_row %}'
        '{% block category_cookies %}{% if category == "analytics" %}'
        '{{ cookie_row("_ga", "Google", "Google Analytics", "2 roky") }}{% endif %}{% endblock %}',
        encoding="utf-8")
    app = make_app(LEGAL_PAGES=["cookies"], CONSENT_CATEGORIES=["analytics", "marketing"])
    from jinja2 import ChoiceLoader, FileSystemLoader
    app.jinja_loader = ChoiceLoader([FileSystemLoader(str(tmp_path / "templates")), app.jinja_loader])
    body = https_client(app).get("/cookies").get_data(as_text=True)
    analytics, marketing = body.split("<h2>Analytické</h2>")[1].split("<h2>Marketingové</h2>")
    assert "<code>_ga</code>" in analytics and "_ga" not in marketing


@pytest.mark.parametrize("pages, message", [
    (["terms"], "unknown page"),
    ({"privacy": "ochrana"}, "must start with /"),
    ("privacy", "must be a list"),
])
def test_invalid_pages_are_refused(make_app, pages, message):
    with pytest.raises(ConfigError, match=message):
        make_app(LEGAL_PAGES=pages)
