"""Configuration loaded from the environment and validated at startup.

Every setting a website needs comes from environment variables (in development
usually from a `.env` file), so the same image runs anywhere and no secret ever
sits in a repository. Validation runs before the Flask app exists: a
misconfigured website refuses to start and lists every problem at once, instead
of failing on the first request that happens to need a missing value.
"""

import os
from collections.abc import Mapping
from typing import Any

from evrima.i18n import DEFAULT_LANGUAGE, LANGUAGES
from evrima.mail import BACKENDS as MAIL_BACKENDS
from evrima.mail import DEFAULT_BACKEND as MAIL_DEFAULT_BACKEND
from evrima.mail import SECURITY_MODES as MAIL_SECURITY_MODES

ENVIRONMENTS = ("production", "development", "testing")

# A SECRET_KEY signs session cookies and CSRF tokens. These values appear in
# tutorials and sample files; a website using one of them would sign its cookies
# with a key anyone can guess.
PLACEHOLDER_SECRETS = frozenset({
    "change-me", "changeme", "secret", "dev", "development", "test",
    "your-secret-key", "replace-me", "please-change-me",
})
MIN_SECRET_KEY_LENGTH = 32

# Production runs behind Caddy, which adds exactly one X-Forwarded-* hop.
DEFAULT_TRUSTED_PROXIES = {"production": 1, "development": 0, "testing": 0}

# Upper bound for a request body. The admin uploads one file per request, so
# this only has to fit the largest allowed file (a 20 MB document) plus form
# overhead, while nobody can tie up a worker by streaming gigabytes at it.
DEFAULT_MAX_CONTENT_LENGTH = 25 * 1024 * 1024

POSTGRES_SCHEMES = ("postgresql://", "postgresql+psycopg://")
REDIS_SCHEMES = ("redis://", "rediss://", "unix://")
MEMORY_STORAGE = "memory://"
# Always accepted besides SITE_HOSTS: health checks run inside the container.
LOCAL_HOSTS = ("localhost", "127.0.0.1")


class ConfigError(RuntimeError):
    """Raised when the configuration is invalid. Carries every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        lines = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(f"Invalid Evrima configuration:\n{lines}")


def load_config(
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read settings from the environment and return a validated Flask config.

    `environ` defaults to `os.environ`; tests pass their own mapping so they
    never depend on the developer's shell. `overrides` lets a website or a test
    set values directly; they are applied before validation, so an override
    cannot sneak an invalid value past the checks.

    Raises ConfigError listing every problem when the result is invalid.
    """
    env = os.environ if environ is None else environ
    environment = env.get("EVRIMA_ENV", "production").strip().lower()
    production = environment == "production"
    problems: list[str] = []

    trusted_proxies = DEFAULT_TRUSTED_PROXIES.get(environment, 0)
    if env.get("TRUSTED_PROXIES", "").strip():
        try:
            trusted_proxies = int(env["TRUSTED_PROXIES"])
        except ValueError:
            problems.append("TRUSTED_PROXIES must be a whole number.")

    redis_url = env.get("REDIS_URL", "").strip()

    # Host names the website answers to. Links in e-mails (password reset,
    # invitations) are built from the request's host, so without this list a
    # forged Host header could make a real reset e-mail point to an attacker's
    # domain. localhost stays allowed for health checks from inside the
    # container; a link to localhost leaks nothing.
    site_hosts = [h.strip().lower() for h in env.get("SITE_HOSTS", "").split(",") if h.strip()]
    trusted_hosts = [*site_hosts, *LOCAL_HOSTS] if site_hosts else None

    smtp_port = 587
    if env.get("SMTP_PORT", "").strip():
        try:
            smtp_port = int(env["SMTP_PORT"])
        except ValueError:
            problems.append("SMTP_PORT must be a whole number.")

    config: dict[str, Any] = {
        "EVRIMA_ENV": environment,
        "SECRET_KEY": env.get("SECRET_KEY", ""),
        "DATABASE_URL": env.get("DATABASE_URL", "").strip(),
        "REDIS_URL": redis_url,
        "TRUSTED_PROXIES": trusted_proxies,
        "SITE_HOSTS": site_hosts,
        # Flask refuses requests for other hosts with 400 Bad Request.
        "TRUSTED_HOSTS": trusted_hosts,
        "TELEMETRY_ENDPOINT": env.get("TELEMETRY_ENDPOINT", "").strip(),
        # Where uploaded files are stored (evrima/media). Empty: the app's
        # instance folder. In production a Docker volume covered by backups.
        "MEDIA_ROOT": env.get("MEDIA_ROOT", "").strip(),
        # Admin language for users who have not chosen one yet.
        "ADMIN_DEFAULT_LANGUAGE": env.get("ADMIN_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE).strip().lower(),
        # E-mail (evrima/mail). Production must deliver for real: the console
        # backend would write login PINs into the log.
        "MAIL_BACKEND": env.get("MAIL_BACKEND", "").strip().lower()
        or MAIL_DEFAULT_BACKEND.get(environment, "smtp"),
        "MAIL_SENDER": env.get("MAIL_SENDER", "").strip(),
        "SMTP_HOST": env.get("SMTP_HOST", "").strip(),
        "SMTP_PORT": smtp_port,
        "SMTP_SECURITY": env.get("SMTP_SECURITY", "starttls").strip().lower(),
        "SMTP_USERNAME": env.get("SMTP_USERNAME", "").strip(),
        "SMTP_PASSWORD": env.get("SMTP_PASSWORD", ""),
        "MAX_CONTENT_LENGTH": DEFAULT_MAX_CONTENT_LENGTH,
        "PREFERRED_URL_SCHEME": "https" if production else "http",
        # The development server runs on plain http://localhost, where a
        # Secure cookie would not be sent back and every form would fail.
        "SESSION_COOKIE_SECURE": environment != "development",
        "SESSION_COOKIE_HTTPONLY": True,
        # In development, edited templates show up on the next request without
        # a restart (and without debug mode and its in-browser debugger).
        "TEMPLATES_AUTO_RELOAD": environment == "development",
        "SESSION_COOKIE_SAMESITE": "Lax",
        # Flask-WTF expires CSRF tokens after an hour by default, so a visitor
        # who leaves an enquiry form open over lunch gets an error on submit.
        # The token stays tied to the session, which is what protects the form.
        "WTF_CSRF_TIME_LIMIT": None,
        "RATELIMIT_STORAGE_URI": redis_url or MEMORY_STORAGE,
        # When Redis is unreachable, let requests through rather than return
        # errors: an unavailable rate limiter must not take the website down.
        # Login lockout does not depend on it; it is counted in the database.
        "RATELIMIT_SWALLOW_ERRORS": True,
        # Extra Content-Security-Policy sources per directive, e.g.
        # {"img-src": ["https://maps.example.com"]}. See security/headers.py.
        "CSP": {},
    }
    if overrides:
        config.update(overrides)

    problems.extend(validate_config(config))
    if problems:
        raise ConfigError(problems)
    return config


def validate_config(config: Mapping[str, Any]) -> list[str]:
    """Return a list of human-readable problems; an empty list means valid."""
    problems: list[str] = []
    environment = config.get("EVRIMA_ENV")
    production = environment == "production"

    if environment not in ENVIRONMENTS:
        problems.append(
            f"EVRIMA_ENV must be one of {', '.join(ENVIRONMENTS)} (got {environment!r}).")

    secret = config.get("SECRET_KEY") or ""
    if not secret:
        problems.append("SECRET_KEY is missing.")
    elif secret.strip().lower() in PLACEHOLDER_SECRETS:
        problems.append("SECRET_KEY is a well-known placeholder value; generate a random one.")
    elif len(secret) < MIN_SECRET_KEY_LENGTH:
        problems.append(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters long.")

    database_url = config.get("DATABASE_URL") or ""
    if not database_url:
        problems.append("DATABASE_URL is missing.")
    elif production and not database_url.startswith(POSTGRES_SCHEMES):
        # SQLite is convenient for development and tests, but production
        # websites run on PostgreSQL (docs/framework.md, Stack).
        problems.append("DATABASE_URL must point to PostgreSQL in production.")

    redis_url = config.get("REDIS_URL") or ""
    if production and not redis_url.startswith(REDIS_SCHEMES):
        problems.append("REDIS_URL must point to Redis in production.")
    elif redis_url and not redis_url.startswith(REDIS_SCHEMES + (MEMORY_STORAGE,)):
        problems.append("REDIS_URL must start with redis://, rediss://, unix:// or memory://.")

    if production and not config.get("SITE_HOSTS"):
        problems.append("SITE_HOSTS is missing: the website's host names, e.g. example.com,www.example.com.")

    trusted_proxies = config.get("TRUSTED_PROXIES")
    if not isinstance(trusted_proxies, int) or trusted_proxies < 0:
        problems.append("TRUSTED_PROXIES must be zero or a positive whole number.")

    if config.get("ADMIN_DEFAULT_LANGUAGE") not in LANGUAGES:
        problems.append(
            f"ADMIN_DEFAULT_LANGUAGE must be one of {', '.join(LANGUAGES)}.")

    backend = config.get("MAIL_BACKEND")
    if backend not in MAIL_BACKENDS:
        problems.append(f"MAIL_BACKEND must be one of {', '.join(MAIL_BACKENDS)}.")
    elif production and backend != "smtp":
        problems.append("MAIL_BACKEND must be smtp in production.")
    if backend == "smtp":
        if not config.get("SMTP_HOST"):
            problems.append("SMTP_HOST is missing.")
        if not config.get("MAIL_SENDER"):
            problems.append("MAIL_SENDER is missing.")
        if config.get("SMTP_SECURITY") not in MAIL_SECURITY_MODES:
            problems.append(f"SMTP_SECURITY must be one of {', '.join(MAIL_SECURITY_MODES)}.")

    return problems


def describe_config(config: Mapping[str, Any]) -> dict[str, str]:
    """Return a summary that is safe to print: no secrets, no passwords."""
    def scheme(url: str) -> str:
        return url.split("://", 1)[0] + "://..." if "://" in url else "(not set)"

    return {
        "environment": str(config.get("EVRIMA_ENV")),
        "database": scheme(config.get("DATABASE_URL") or ""),
        "redis": scheme(config.get("REDIS_URL") or ""),
        "trusted proxies": str(config.get("TRUSTED_PROXIES")),
        "hosts": ", ".join(config.get("SITE_HOSTS") or []) or "(any)",
        "telemetry": "on" if config.get("TELEMETRY_ENDPOINT") else "off",
        "mail": (f"{config.get('MAIL_BACKEND')} via {config.get('SMTP_HOST')}"
                 if config.get("MAIL_BACKEND") == "smtp" else str(config.get("MAIL_BACKEND"))),
    }
