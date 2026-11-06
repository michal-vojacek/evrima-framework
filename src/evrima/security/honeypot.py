"""Spam protection for public forms without a third-party CAPTCHA.

Two cheap checks catch the simple bots that fill in every field they find and
submit at once (docs/framework.md, "Security baseline"):

- a trap field hidden from people (the `hidden` attribute hides it from screen
  readers too, and no inline style is needed under the strict CSP); a person
  never fills it in, a naive bot does;
- a signed time stamp of when the form was rendered; a person needs a few
  seconds to fill in a form, a bot posts within one. The signature stops a bot
  from sending a stamp of its own.

A form that fails the check should look accepted (the bot learns nothing) and
send nothing. This does not stop a determined attacker; the rate limit on the
form view and the CSRF token do the rest.

In a template: `{{ honeypot("contact") }}` inside the <form>. In the view:
`if honeypot.looks_like_bot(request.form, "contact"): ...`.
"""

import time

from flask import Flask, current_app
from itsdangerous import BadSignature, TimestampSigner
from markupsafe import Markup

# The trap's name looks like a field worth filling in. Websites must not use
# these names for their own fields.
TRAP_FIELD = "homepage"
STAMP_FIELD = "form_stamp"

# Filling in even the shortest form takes a person longer than this.
MIN_SECONDS = 3
# A stamp older than this is refused, so a bot cannot fetch the form once and
# reuse its stamp for ever (code review 2026-11-06). Long, because a refused
# person is told nothing: a form left open in a tab over a weekend must still work.
MAX_SECONDS = 7 * 24 * 3600


def _now() -> float:
    """The current time; a function so tests can move the clock."""
    return time.time()


def _signer(form: str) -> TimestampSigner:
    """A signer bound to the secret key and to one form.

    The form name is part of the salt, so a stamp taken from one form cannot be
    replayed on another.
    """
    return TimestampSigner(current_app.config["SECRET_KEY"], salt=f"evrima.honeypot.{form}")


def fields(form: str) -> Markup:
    """The hidden markup to put inside a public <form>."""
    stamp = _signer(form).sign(str(int(_now()))).decode()
    return Markup(
        '<div hidden>'
        f'<input type="text" name="{TRAP_FIELD}" value="" tabindex="-1" autocomplete="off">'
        '</div>'
        '<input type="hidden" name="{0}" value="{1}">'
    ).format(STAMP_FIELD, stamp)


def looks_like_bot(data, form: str, min_seconds: float = MIN_SECONDS,
                   max_seconds: float = MAX_SECONDS) -> bool:
    """True when the submitted `data` (e.g. request.form) was most likely sent by a bot.

    Reasons: the trap is filled in, the stamp is missing, forged or older than
    `max_seconds`, or the form came back faster than a person could fill it in.
    """
    if (data.get(TRAP_FIELD) or "").strip():
        return True
    stamp = data.get(STAMP_FIELD) or ""
    try:
        rendered_at = int(_signer(form).unsign(stamp).decode())
    except (BadSignature, ValueError):
        return True
    age = _now() - rendered_at
    return not min_seconds <= age <= max_seconds


def init_app(app: Flask) -> None:
    """Make `honeypot(form)` available in templates."""
    app.jinja_env.globals["honeypot"] = fields
