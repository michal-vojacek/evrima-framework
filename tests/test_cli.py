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
