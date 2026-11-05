"""Sending e-mail through the configured backend."""

import smtplib

import pytest

from conftest import BASE_ENV, PRODUCTION_ENV
from evrima import ConfigError, mail
from evrima.config import load_config


class FakeSMTP:
    """Stands in for smtplib.SMTP and records what the mail module does."""

    sent = []

    def __init__(self, host, port, timeout):
        self.calls = [("connect", host, port, timeout)]

    def starttls(self, context):
        self.calls.append(("starttls",))

    def login(self, username, password):
        self.calls.append(("login", username))

    def send_message(self, message):
        FakeSMTP.sent.append((self.calls, message))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_memory_backend_keeps_messages(app):
    with app.app_context():
        mail.send("klient@example.com", "PIN", "Your PIN is 123456.")
        [message] = mail.outbox()
    assert message["To"] == "klient@example.com"
    assert message["Subject"] == "PIN"
    assert "123456" in message.get_content()


def test_console_backend_prints_the_message(make_app, capsys):
    app = make_app(env={"MAIL_BACKEND": "console"})
    with app.app_context():
        mail.send("klient@example.com", "PIN", "Your PIN is 123456.")
    assert "123456" in capsys.readouterr().err


def test_line_break_in_header_is_rejected(app):
    # Header injection: a subject with a line break could add a Bcc header.
    with app.app_context(), pytest.raises(ValueError):
        mail.send("klient@example.com", "Hi\nBcc: someone@example.com", "text")


def test_smtp_uses_starttls_and_login(make_app, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    app = make_app(env={
        "MAIL_BACKEND": "smtp", "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
        "SMTP_USERNAME": "web@example.com", "SMTP_PASSWORD": "secret",
        "MAIL_SENDER": "web@example.com"})
    with app.app_context():
        mail.send("klient@example.com", "Hello", "Text")
    [(calls, message)] = FakeSMTP.sent
    assert calls == [("connect", "smtp.example.com", 587, mail.SMTP_TIMEOUT_SECONDS),
                     ("starttls",), ("login", "web@example.com")]
    assert message["From"] == "web@example.com"


def test_unreachable_smtp_raises_mail_error(make_app):
    app = make_app(env={
        "MAIL_BACKEND": "smtp", "SMTP_HOST": "127.0.0.1", "SMTP_PORT": "9",
        "MAIL_SENDER": "web@example.com"})
    with app.app_context(), pytest.raises(mail.MailError):
        mail.send("klient@example.com", "Hello", "Text")


def test_production_refuses_console_mail():
    with pytest.raises(ConfigError) as caught:
        load_config(environ={**PRODUCTION_ENV, "MAIL_BACKEND": "console"})
    assert "MAIL_BACKEND must be smtp in production." in caught.value.problems


def test_smtp_needs_host_and_sender():
    with pytest.raises(ConfigError) as caught:
        load_config(environ={**BASE_ENV, "MAIL_BACKEND": "smtp"})
    assert "SMTP_HOST is missing." in caught.value.problems
    assert "MAIL_SENDER is missing." in caught.value.problems
