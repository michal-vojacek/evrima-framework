"""Shared fixtures: apps are built from an explicit environment, never from the shell."""

import re

import pytest

from evrima import create_app, mail
from evrima.auth import credentials
from evrima.auth.models import Administrator
from evrima.db import db, migrations, utcnow

# A valid testing configuration: SQLite in memory and in-process rate limits,
# so the suite needs neither PostgreSQL nor Redis.
BASE_ENV = {
    "EVRIMA_ENV": "testing",
    "SECRET_KEY": "test-secret-key-" + "x" * 32,
    "DATABASE_URL": "sqlite://",
    "REDIS_URL": "memory://",
}

PRODUCTION_ENV = {
    "EVRIMA_ENV": "production",
    "SECRET_KEY": "production-secret-key-" + "y" * 32,
    # Engines and Redis clients connect lazily, so these need no server unless
    # a test actually queries them.
    "DATABASE_URL": "postgresql+psycopg://user:password@localhost/evrima",
    "REDIS_URL": "redis://localhost:6379/0",
    "SITE_HOSTS": "example.com,www.example.com",
    "SMTP_HOST": "smtp.example.com",
    "MAIL_SENDER": "web@example.com",
}

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery staple"


@pytest.fixture
def make_app(tmp_path):
    """Return a builder for apps with a chosen environment, overrides and blueprints.

    Testing apps get their tables from the real migrations, so every test
    also proves that the migrations work. Uploaded files go to the test's own
    temporary folder.
    """
    def build(env=None, blueprints=(), modules=(), import_name="fixture_site", migrate=True, **overrides):
        environ = {**BASE_ENV, "MEDIA_ROOT": str(tmp_path / "media"), **(env or {})}
        app = create_app(
            import_name, blueprints=blueprints, modules=modules, environ=environ,
            config_overrides=overrides or None)
        if migrate and environ["EVRIMA_ENV"] != "production":
            with app.app_context():
                migrations.upgrade()
        return app
    return build


@pytest.fixture
def app(make_app):
    """A testing app built on the fixture website."""
    return make_app()


def https_client(app):
    """Return a test client that talks HTTPS, so Secure cookies round-trip."""
    client = app.test_client()
    client.environ_base["wsgi.url_scheme"] = "https"
    return client


@pytest.fixture
def client(app):
    """An HTTPS test client for the default testing app."""
    return https_client(app)


def add_admin(app, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, **fields):
    """Create an administrator directly in the database and return its id."""
    with app.app_context():
        admin = Administrator(
            email=email, password_hash=credentials.hash_password(password) if password else None,
            password_changed_at=utcnow(), **fields)
        db.session.add(admin)
        db.session.commit()
        return admin.id


def csrf_token(client, path="/admin/login"):
    """The CSRF token from a page's meta tag."""
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def last_pin(app):
    """The PIN from the last e-mail in the outbox."""
    with app.app_context():
        body = mail.outbox()[-1].get_content()
    return re.search(r"\b(\d{6})\b", body).group(1)


def log_in(app, client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    """Go through the whole login (password, then the e-mailed PIN)."""
    token = csrf_token(client)
    response = client.post("/admin/login", data={"csrf_token": token, "email": email, "password": password})
    if response.headers.get("Location", "").endswith("/admin/login/verify"):
        response = client.post("/admin/login/verify", data={
            "csrf_token": token, "method": "pin", "code": last_pin(app)})
    return response


@pytest.fixture
def admin_client(app):
    """An HTTPS client logged in as the test administrator."""
    add_admin(app)
    client = https_client(app)
    response = log_in(app, client)
    assert response.status_code == 302, response.get_data(as_text=True)
    return client
