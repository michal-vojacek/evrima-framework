"""`flask evrima` commands."""

from conftest import BASE_ENV
from evrima import get_version


def test_version_command(app):
    result = app.test_cli_runner().invoke(args=["evrima", "version"])
    assert result.exit_code == 0
    assert result.output.strip() == get_version()


def test_check_config_command_prints_no_secrets(app):
    result = app.test_cli_runner().invoke(args=["evrima", "check-config"])
    assert result.exit_code == 0
    assert "configuration is valid" in result.output
    assert BASE_ENV["SECRET_KEY"] not in result.output


def test_jobs_run_in_their_own_context_and_stop_on_sigterm(app, monkeypatch):
    """Each job gets a fresh database session; SIGTERM ends the loop after the current job."""
    import signal

    from flask import g

    from evrima import media
    from evrima.db import db
    from evrima.telemetry import ship

    handlers, sessions = {}, []
    monkeypatch.setattr(signal, "signal", lambda signum, handler: handlers.__setitem__(signum, handler))

    def fake_ship():
        sessions.append(db.session)
        return 2

    def fake_cleanup():
        sessions.append(db.session)
        assert "evrima_db_session" in g
        handlers[signal.SIGTERM](signal.SIGTERM, None)    # docker stop arrives during the job
        raise RuntimeError("database restarted")
    monkeypatch.setattr(ship, "ship", fake_ship)
    monkeypatch.setattr(media, "cleanup", fake_cleanup)
    from evrima.auth import cleanup as auth_cleanup
    monkeypatch.setattr(auth_cleanup, "cleanup", lambda: 3)

    result = app.test_cli_runner().invoke(args=["evrima", "jobs"])
    assert result.exit_code == 0
    assert "Telemetry events sent: 2." in result.output
    assert "Unused files removed failed: RuntimeError: database restarted" in result.output
    assert "Old login records removed: 3." in result.output
    assert result.output.rstrip().endswith("Jobs stopped.")
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
