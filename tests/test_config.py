"""Configuration loading and startup validation."""

import pytest

from conftest import BASE_ENV, PRODUCTION_ENV
from evrima import ConfigError, create_app
from evrima.config import describe_config, load_config


def problems_for(env, **overrides):
    """Return the list of problems ConfigError reports for `env`."""
    with pytest.raises(ConfigError) as caught:
        load_config(environ=env, overrides=overrides or None)
    return caught.value.problems


def test_valid_testing_config_loads():
    config = load_config(environ=BASE_ENV)
    assert config["EVRIMA_ENV"] == "testing"
    assert config["RATELIMIT_STORAGE_URI"] == "memory://"


def test_environment_defaults_to_production():
    env = {key: value for key, value in PRODUCTION_ENV.items() if key != "EVRIMA_ENV"}
    assert load_config(environ=env)["EVRIMA_ENV"] == "production"


def test_missing_secret_key_is_reported():
    env = {key: value for key, value in BASE_ENV.items() if key != "SECRET_KEY"}
    assert "SECRET_KEY is missing." in problems_for(env)


def test_placeholder_secret_key_is_rejected():
    problems = problems_for({**BASE_ENV, "SECRET_KEY": "change-me"})
    assert any("placeholder" in problem for problem in problems)


def test_short_secret_key_is_rejected():
    problems = problems_for({**BASE_ENV, "SECRET_KEY": "short-but-random-9f3k"})
    assert any("at least 32 characters" in problem for problem in problems)


def test_every_problem_is_reported_at_once():
    problems = problems_for({"EVRIMA_ENV": "testing"})
    assert "SECRET_KEY is missing." in problems
    assert "DATABASE_URL is missing." in problems


def test_unknown_environment_is_rejected():
    problems = problems_for({**BASE_ENV, "EVRIMA_ENV": "staging"})
    assert any("EVRIMA_ENV" in problem for problem in problems)


def test_production_requires_postgres_and_redis():
    env = {**PRODUCTION_ENV, "DATABASE_URL": "sqlite:///site.db", "REDIS_URL": "memory://"}
    problems = problems_for(env)
    assert "DATABASE_URL must point to PostgreSQL in production." in problems
    assert "REDIS_URL must point to Redis in production." in problems


def test_production_defaults():
    config = load_config(environ=PRODUCTION_ENV)
    assert config["TRUSTED_PROXIES"] == 1
    assert config["SESSION_COOKIE_SECURE"] is True
    assert config["PREFERRED_URL_SCHEME"] == "https"
    assert config["RATELIMIT_STORAGE_URI"] == PRODUCTION_ENV["REDIS_URL"]


def test_development_cookie_is_not_secure():
    config = load_config(environ={**BASE_ENV, "EVRIMA_ENV": "development"})
    assert config["SESSION_COOKIE_SECURE"] is False


def test_overrides_are_validated_too():
    problems = problems_for(BASE_ENV, SECRET_KEY="dev")
    assert any("placeholder" in problem for problem in problems)


def test_invalid_trusted_proxies_is_reported():
    problems = problems_for({**BASE_ENV, "TRUSTED_PROXIES": "two"})
    assert "TRUSTED_PROXIES must be a whole number." in problems


def test_describe_config_hides_credentials():
    summary = describe_config(load_config(environ=PRODUCTION_ENV))
    text = " ".join(summary.values())
    assert "password" not in text
    assert PRODUCTION_ENV["SECRET_KEY"] not in text
    assert summary["database"] == "postgresql+psycopg://..."


def test_create_app_refuses_invalid_config():
    with pytest.raises(ConfigError):
        create_app("fixture_site", environ={"EVRIMA_ENV": "testing"})


def test_production_requires_site_hosts():
    env = {key: value for key, value in PRODUCTION_ENV.items() if key != "SITE_HOSTS"}
    with pytest.raises(ConfigError) as error:
        load_config(env)
    assert any("SITE_HOSTS" in problem for problem in error.value.problems)


def test_requests_for_foreign_hosts_are_refused():
    """A forged Host could otherwise steer the links in password reset e-mails."""
    from evrima import create_app

    app = create_app("fixture_site", environ={**BASE_ENV, "SITE_HOSTS": "example.com"})
    client = app.test_client()
    assert client.get("/health", base_url="https://evil.example").status_code == 400
    assert client.get("/", base_url="https://example.com").status_code != 400
    assert client.get("/", base_url="http://localhost").status_code != 400


def test_a_foreign_or_upper_case_host_gets_a_plain_400(make_app):
    """The website's error page may call url_for, which needs routing; the answer must still be a 400."""
    from jinja2 import ChoiceLoader, DictLoader

    app = make_app(env={"SITE_HOSTS": "example.com"})
    app.jinja_env.loader = ChoiceLoader([DictLoader({"errors/error.html": "{{ url_for('evrima_health.health') }}"}),
                                         app.jinja_env.loader])
    client = app.test_client()
    for host in ("evil.example", "EXAMPLE.COM", "example.com."):
        response = client.get("/", base_url="https://example.com", headers={"Host": host})
        assert response.status_code == 400
        assert response.mimetype == "text/plain" and response.get_data(as_text=True).startswith("400 Bad Request")
    assert client.get("/missing", base_url="https://example.com").status_code == 404
