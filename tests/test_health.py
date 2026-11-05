"""Health check endpoint."""

from conftest import https_client


def test_health_ok_with_working_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "checks": {"database": "ok", "redis": "skipped"}}
    assert response.headers["Cache-Control"] == "no-store"


def test_health_fails_when_database_is_unreachable(make_app, tmp_path):
    # SQLite cannot create a file in a directory that does not exist.
    missing = tmp_path / "missing" / "site.sqlite3"
    app = make_app(env={"DATABASE_URL": f"sqlite:///{missing.as_posix()}"}, migrate=False)
    response = https_client(app).get("/health")
    assert response.status_code == 503
    assert response.json["checks"]["database"] == "fail"
    # The error detail (here a path, in production a connection string) stays
    # in the log and never reaches the response.
    assert "missing" not in response.get_data(as_text=True)
