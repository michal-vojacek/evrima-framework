"""Health check endpoint, used by Docker and by `docker_deploy`.

A deploy waits for the new version to answer 200 here; if it does not, the old
version keeps running (docs/framework.md, "Distribution and deployment"). The
response names the failing dependency but never the error itself, which could
contain a connection string; the error goes to the log instead.
"""

from flask import Blueprint, current_app, jsonify

from evrima import redis_client
from evrima.db import db
from evrima.security import limiter

bp = Blueprint("evrima_health", __name__)


@bp.get("/health")
@limiter.exempt
def health():
    """Return 200 when the database and Redis respond, 503 otherwise."""
    checks = {"database": _check(db.ping, "database")}

    client = redis_client.get_client()
    # No client means Redis is not configured (development or tests with
    # memory:// storage); production config validation guarantees one.
    checks["redis"] = _check(client.ping, "redis") if client is not None else "skipped"

    healthy = all(result != "fail" for result in checks.values())
    response = jsonify(status="ok" if healthy else "fail", checks=checks)
    response.status_code = 200 if healthy else 503
    # A cached "ok" would hide an outage from the deploy and the monitoring.
    response.headers["Cache-Control"] = "no-store"
    return response


def _check(probe, name: str) -> str:
    """Run `probe` and return "ok", or log the error and return "fail"."""
    try:
        probe()
        return "ok"
    except Exception:
        current_app.logger.exception("Health check failed: %s", name)
        return "fail"
