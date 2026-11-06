"""robots.txt, sitemap.xml, security.txt, canonical URLs and JSON-LD."""

import json
from datetime import UTC, datetime, timedelta

from flask import Blueprint, render_template_string

from conftest import PRODUCTION_ENV, https_client
from evrima import seo

pages = Blueprint("pages", __name__)


@pages.get("/")
def home():
    return render_template_string("{{ canonical_url() }}|{{ data | json_ld }}",
                                  data={"@type": "Person", "name": "<!--<script></script><b>x</b> & more"})


@pages.get("/o-mne")
def about():
    return "about"


SEO = {"SITE_URL": "https://example.com/", "SITEMAP": ["pages.home", "pages.about"],
       "SECURITY_CONTACT": "mailto:security@example.com"}


def test_robots_allows_all_but_the_admin_and_names_the_sitemap(make_app):
    app = make_app(blueprints=[pages], **SEO, ROBOTS_BLOCKED_AGENTS=["GPTBot", "CCBot"])
    text = https_client(app).get("/robots.txt").get_data(as_text=True)
    assert text == ("User-agent: GPTBot\nDisallow: /\n\nUser-agent: CCBot\nDisallow: /\n\n"
                    "User-agent: *\nAllow: /\nDisallow: /admin/\n\nSitemap: https://example.com/sitemap.xml\n")


def test_robots_without_a_sitemap(app):
    text = https_client(app).get("/robots.txt").get_data(as_text=True)
    assert "Sitemap" not in text and "Disallow: /admin/" in text


def test_sitemap_lists_the_chosen_pages(make_app):
    app = make_app(blueprints=[pages], **SEO)
    response = https_client(app).get("/sitemap.xml")
    assert response.mimetype == "application/xml"
    body = response.get_data(as_text=True)
    assert "<loc>https://example.com/</loc>" in body and "<loc>https://example.com/o-mne</loc>" in body


def test_no_sitemap_without_pages(app):
    assert https_client(app).get("/sitemap.xml").status_code == 404


def test_security_txt(make_app):
    app = make_app(blueprints=[pages], **SEO)
    text = https_client(app).get("/.well-known/security.txt").get_data(as_text=True)
    fields = dict(line.split(": ", 1) for line in text.strip().splitlines())
    assert fields["Contact"] == "mailto:security@example.com"
    assert fields["Canonical"] == "https://example.com/.well-known/security.txt"
    assert fields["Preferred-Languages"] == "cs, en"
    expires = datetime.fromisoformat(fields["Expires"])
    assert timedelta(days=150) < expires - datetime.now(UTC) < timedelta(days=365)


def test_no_security_txt_without_a_contact(app):
    assert https_client(app).get("/.well-known/security.txt").status_code == 404


def test_canonical_url_and_json_ld_cannot_break_out(make_app):
    app = make_app(blueprints=[pages], **SEO)
    html = https_client(app).get("/?utm_source=x").get_data(as_text=True)
    canonical, block = html.split("|")
    assert canonical == "https://example.com/"
    assert block.startswith('<script type="application/ld+json">')
    assert block.count("</script>") == 1 and block.count("<") == 2   # only the block's own tags
    assert r"\u003c/script\u003e" in block and r"\u003c!--" in block
    data = json.loads(block.removeprefix('<script type="application/ld+json">').removesuffix("</script>"))
    assert data["name"] == "<!--<script></script><b>x</b> & more"


def test_production_site_url_comes_from_site_hosts(make_app):
    app = make_app(env=PRODUCTION_ENV, migrate=False)
    with app.test_request_context(base_url="https://example.com"):
        assert seo.site_url() == "https://example.com"
