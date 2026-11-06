"""Application factory: builds a website's Flask app on top of Evrima.

A website is an ordinary Python package. It calls `create_app(__name__, ...)`,
so Flask treats the website package as the application: its `templates/` and
`static/` folders come first. Evrima adds its own templates and static files
through a blueprint, which Flask searches only after the application's folders,
so a website can override any default template that is meant to be overridden.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from flask import Blueprint, Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from evrima import (admin, auth, cli, consent, editor, errors, health, i18n, legal, mail, media, redis_client,
                    security, seo, static_files, telemetry)
from evrima.config import load_config
from evrima.db import db, migrations
from evrima.media import views as media_views
from evrima.modules import register as register_modules

# Framework templates live under templates/evrima/ so their names cannot clash
# with a website's templates; static files are served under /_evrima/static/.
framework = Blueprint(
    "evrima",
    __name__,
    template_folder="templates",
    static_folder="static/evrima",
    static_url_path="/_evrima/static",
)


def create_app(
    import_name: str,
    *,
    blueprints: Iterable[Blueprint] = (),
    modules: Iterable[Any] = (),
    config_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Flask:
    """Build and return the Flask app of a website.

    import_name: the website package, normally `__name__` of its __init__.py.
    blueprints: the website's routes, registered after the framework's own.
    modules: the website's modules to enable (docs/modules.md).
    config_overrides: settings applied on top of the environment, still validated.
    environ: environment to read instead of os.environ (used by tests).

    Raises evrima.config.ConfigError when the configuration is invalid, so a
    misconfigured website fails at startup instead of at the first request.
    """
    config = load_config(environ=environ, overrides=config_overrides)

    app = Flask(import_name)
    app.config.update(config)

    proxies = app.config["TRUSTED_PROXIES"]
    if proxies:
        # Behind Caddy the client address arrives in X-Forwarded-For. Trusting
        # exactly as many hops as there are proxies keeps request.remote_addr
        # honest; trusting more would let a visitor forge their own IP and
        # dodge rate limits and login lockout.
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)

    db.init_app(app)
    migrations.init_app(app)
    redis_client.init_app(app)
    mail.init_app(app)
    security.init_app(app)
    i18n.init_app(app)
    editor.init_app(app)
    media.init_app(app)

    app.register_blueprint(framework)
    app.register_blueprint(health.bp)
    telemetry.init_app(app)
    consent.init_app(app)
    legal.init_app(app)
    static_files.init_app(app)
    seo.init_app(app)
    auth.init_app(app)
    admin.init_app(app)
    app.register_blueprint(media_views.public)
    app.register_blueprint(media_views.admin)
    register_modules(app, modules)
    errors.register(app)
    cli.register(app)

    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    return app
