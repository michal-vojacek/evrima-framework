"""E-mails of the admin login, in the recipient's language.

Each message names the website (its host name), because one person may
administer several websites built on Evrima.
"""

from flask import request, url_for

from evrima import mail
from evrima.auth.models import Administrator
from evrima.i18n import translate_for


def _site() -> str:
    """The website's host name, e.g. example.com."""
    return request.host.split(":")[0]


def _send(admin: Administrator, key: str, **params) -> None:
    """Send the message `auth.email.<key>` (subject and body) to `admin`."""
    params = {"site": _site(), **params}
    lang = admin.language
    subject = translate_for(lang, f"auth.email.{key}.subject", **params)
    body = translate_for(lang, f"auth.email.{key}.body", **params)
    signature = translate_for(lang, "auth.email.signature", **params)
    mail.send(admin.email, subject, f"{body}\n\n{signature}\n")


def send_pin(admin: Administrator, pin: str) -> None:
    """The login PIN, with the warning that doubles as the new-device notice."""
    _send(admin, "pin", pin=pin, reset_url=url_for("evrima_auth.forgot_password", _external=True))


def send_reset(admin: Administrator, token: str) -> None:
    """A link to set a new password."""
    _send(admin, "reset", url=url_for("evrima_auth.set_password", token=token, _external=True))


def send_invite(admin: Administrator, token: str, invited_by: Administrator) -> None:
    """An invitation to the admin, with a link to choose a password."""
    _send(admin, "invite", inviter=invited_by.display_name,
          url=url_for("evrima_auth.set_password", token=token, _external=True))


def send_totp_login_notice(admin: Administrator) -> None:
    """A login with a TOTP code sends no PIN, so this e-mail tells the owner about it."""
    _send(admin, "totp_login", browser=request.user_agent.string[:120] or "?",
          reset_url=url_for("evrima_auth.forgot_password", _external=True))
