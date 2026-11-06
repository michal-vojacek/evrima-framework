"""Sending e-mail: PINs, notifications, enquiries from forms.

E-mail goes out over the SMTP of an external service (e.g. Seznam Email Profi,
Gmail); Evrima runs no mail server (docs/framework.md, "Sending e-mail").

Backends, chosen by MAIL_BACKEND:

- `smtp`: real delivery; the only backend allowed in production,
- `console`: development; the message is printed to the server's console, so
  a reset link can be read without a mail account,
- `memory`: tests; messages are kept in `outbox()`.
"""

import smtplib
import ssl
import sys
from email.message import EmailMessage

from flask import Flask, current_app

BACKENDS = ("smtp", "console", "memory")
SECURITY_MODES = ("starttls", "ssl")
DEFAULT_BACKEND = {"production": "smtp", "development": "console", "testing": "memory"}

# Long enough for a slow provider, short enough that a dead one does not hold
# a worker (and the waiting user) for minutes.
SMTP_TIMEOUT_SECONDS = 15

_OUTBOX_KEY = "evrima.mail.outbox"


class MailError(RuntimeError):
    """Raised when a message could not be handed over to the mail service."""


def init_app(app: Flask) -> None:
    """Prepare the in-memory outbox (used by the memory backend)."""
    app.extensions[_OUTBOX_KEY] = []


def send(to: str, subject: str, text: str, *, reply_to: str | None = None) -> None:
    """Send a plain-text message to one recipient.

    Plain text only: it reads well in every client, cannot carry tracking
    pixels and leaves no room for HTML injection. Header values are checked by
    EmailMessage itself, which rejects line breaks (header injection).

    Raises MailError when the message cannot be delivered to the SMTP server.
    """
    config = current_app.config
    message = EmailMessage()
    message["From"] = config["MAIL_SENDER"]
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(text)

    backend = config["MAIL_BACKEND"]
    if backend == "memory":
        current_app.extensions[_OUTBOX_KEY].append(message)
    elif backend == "console":
        # Printed rather than logged: Flask's logger drops INFO messages
        # unless debug mode is on, and the point is to see the e-mail.
        print(f"--- E-mail to {to}: {subject} ---\n{text}\n--- end of e-mail ---",
              file=sys.stderr, flush=True)
    else:
        _send_smtp(message)


def outbox() -> list[EmailMessage]:
    """Messages sent with the memory backend (tests)."""
    return current_app.extensions[_OUTBOX_KEY]


def _send_smtp(message: EmailMessage) -> None:
    """Deliver `message` over SMTP with TLS; never logs the password."""
    config = current_app.config
    host, port = config["SMTP_HOST"], config["SMTP_PORT"]
    context = ssl.create_default_context()
    try:
        if config["SMTP_SECURITY"] == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
            server.starttls(context=context)
        with server:
            if config["SMTP_USERNAME"]:
                server.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"])
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        current_app.logger.error(
            "Sending e-mail via %s:%s failed: %s", host, port, type(error).__name__)
        raise MailError("The e-mail could not be sent.") from error
