"""Security headers, CSRF protection and proxy handling."""

import re

from flask import Blueprint, request
from flask_wtf.csrf import generate_csrf

from conftest import PRODUCTION_ENV, https_client
from evrima.security.headers import build_csp

probe = Blueprint("probe", __name__)


@probe.get("/probe")
def probe_page():
    """A page that touches nothing but the request."""
    return "probe"


@probe.get("/probe/token")
def probe_token():
    """Hand out a CSRF token, the way a form page would embed one."""
    return generate_csrf()


@probe.post("/probe/submit")
def probe_submit():
    """A form target protected by the global CSRF check."""
    return "accepted"


@probe.get("/probe/ip")
def probe_ip():
    """Echo the client address the app believes in."""
    return request.remote_addr or ""


@probe.get("/probe/framed")
def probe_framed():
    """A view that sets its own CSP, which the framework must respect."""
    return "framed", 200, {"Content-Security-Policy": "frame-ancestors https://example.com"}


def test_security_headers_are_added(make_app):
    client = https_client(make_app(blueprints=[probe]))
    headers = client.get("/probe").headers
    assert headers["Content-Security-Policy"] == build_csp()
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in headers["Permissions-Policy"]
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"


def test_default_csp_allows_nothing_inline():
    csp = build_csp()
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert re.search(r"script-src 'self'(;|$)", csp)
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_extra_csp_sources_are_merged_not_replacing(make_app):
    app = make_app(blueprints=[probe], CSP={"img-src": ["https://maps.example.com"]})
    csp = https_client(app).get("/probe").headers["Content-Security-Policy"]
    assert "img-src 'self' https://maps.example.com" in csp
    assert "script-src 'self'" in csp


def test_view_can_set_its_own_header(make_app):
    client = https_client(make_app(blueprints=[probe]))
    csp = client.get("/probe/framed").headers["Content-Security-Policy"]
    assert csp == "frame-ancestors https://example.com"


def test_hsts_only_in_production(make_app):
    testing = https_client(make_app(blueprints=[probe]))
    assert "Strict-Transport-Security" not in testing.get("/probe").headers

    production = https_client(make_app(env=PRODUCTION_ENV, blueprints=[probe]))
    hsts = production.get("/probe").headers["Strict-Transport-Security"]
    assert hsts == "max-age=31536000; includeSubDomains"


def test_post_without_csrf_token_is_rejected(make_app):
    client = https_client(make_app(blueprints=[probe]))
    response = client.post("/probe/submit", data={"name": "x"})
    assert response.status_code == 400


def test_post_with_csrf_token_is_accepted(make_app):
    client = https_client(make_app(blueprints=[probe]))
    token = client.get("/probe/token").get_data(as_text=True)
    response = client.post("/probe/submit", data={"csrf_token": token})
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "accepted"


def test_forwarded_ip_is_trusted_behind_one_proxy(make_app):
    client = https_client(make_app(env={"TRUSTED_PROXIES": "1"}, blueprints=[probe]))
    response = client.get("/probe/ip", headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.get_data(as_text=True) == "203.0.113.7"


def test_forwarded_ip_is_ignored_without_proxy(make_app):
    client = https_client(make_app(blueprints=[probe]))
    response = client.get("/probe/ip", headers={"X-Forwarded-For": "203.0.113.7"})
    assert response.get_data(as_text=True) != "203.0.113.7"


def test_forged_extra_hop_does_not_win(make_app):
    # A visitor sends their own X-Forwarded-For; Caddy appends the real address.
    client = https_client(make_app(env={"TRUSTED_PROXIES": "1"}, blueprints=[probe]))
    response = client.get(
        "/probe/ip", headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.7"})
    assert response.get_data(as_text=True) == "203.0.113.7"
