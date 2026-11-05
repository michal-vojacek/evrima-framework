"""Public pages of the admin login: login, verification, logout, forgotten password.

Login has two steps (docs/framework.md, "Admin login"):

1. e-mail and password; a browser trusted in the last 10 days is let in here;
2. otherwise a six-digit PIN sent by e-mail, or a TOTP code if the user has
   set up an authenticator app.

Between the steps, Flask's session holds only the pending login (who and
which challenge), never a secret. Everything that limits the second step
lives in the database, not in that cookie, because an old cookie can be
replayed: the pending login lasts only as long as its challenge (10 minutes),
a password change cancels it, at most 5 wrong codes (PIN or TOTP) are
accepted per challenge, and at most 5 challenges per hour per account. Error
messages never reveal whether an e-mail belongs to an administrator.
"""

import re
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, update
from werkzeug.wrappers.response import Response

from evrima import i18n
from evrima.admin.navigation import safe_next
from evrima.auth import audit, credentials, emails, lockout, sessions, totp
from evrima.auth.models import AccountLink, Administrator, LoginChallenge
from evrima.db import db, utcnow
from evrima.i18n import translate as t
from evrima.mail import MailError
from evrima.security import limiter

bp = Blueprint("evrima_auth", __name__, url_prefix="/admin")

PENDING_KEY = "evrima_pending_login"
PIN_LIFETIME = timedelta(minutes=10)
# Wrong codes per challenge, PIN and TOTP together. Without a limit per
# challenge, a stolen password plus many IP addresses would let an attacker
# guess a TOTP code in hours (the lockout counts per e-mail and IP).
PIN_ATTEMPTS = 5
# New challenges per account and hour, so that "send a new code" cannot
# hand out fresh attempts without end.
CHALLENGES_PER_HOUR = 5
RESET_LIFETIME = timedelta(hours=1)
INVITE_LIFETIME = timedelta(days=3)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_email(value: str | None) -> str:
    """Trim and lower-case an e-mail; addresses are compared case-insensitively."""
    return (value or "").strip().lower()[:254]


# --- Step 1: e-mail and password --------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("30 per minute", methods=["POST"])
def login():
    """E-mail and password; then straight in on a trusted device, or on to the PIN."""
    next_url = safe_next(request.values.get("next"))
    if sessions.current_admin() is not None:
        return redirect(next_url)
    if request.method == "GET":
        return render_template("evrima/admin/auth/login.html", next=next_url, email="")

    email = normalise_email(request.form.get("email"))
    password = request.form.get("password", "")[: credentials.PASSWORD_MAX_LENGTH + 1]

    until = lockout.locked_until(email)
    if until is not None:
        minutes = max(1, int((until - utcnow()).total_seconds() // 60) + 1)
        return _login_error(t("auth.login.locked", minutes=minutes), email, next_url, 429)

    admin = db.session.scalar(select(Administrator).where(Administrator.email == email))
    if not credentials.verify_password(admin.password_hash if admin else None, password):
        lockout.record_failure(email)
        audit.record("login.failed", admin=admin, email=email)
        return _login_error(t("auth.login.failed"), email, next_url)

    if credentials.needs_rehash(admin.password_hash):
        admin.password_hash = credentials.hash_password(password)
        db.session.commit()

    if sessions.trusted_device(admin) is not None:
        lockout.clear(email)
        return _finish_login(admin, next_url, via="device")
    return _start_challenge(admin, next_url)


def _login_error(message: str, email: str, next_url: str, status: int = 200):
    """Show the login form again with an error and the e-mail filled in."""
    return render_template(
        "evrima/admin/auth/login.html", error=message, email=email, next=next_url), status


class TooManyChallenges(Exception):
    """The account asked for more codes in the last hour than allowed."""


def _start_challenge(admin: Administrator, next_url: str):
    """Create a PIN, e-mail it and move to the verification step."""
    try:
        _new_challenge(admin)
    except TooManyChallenges:
        audit.record("login.too_many_codes", admin=admin)
        return _login_error(t("auth.login.too_many_codes"), admin.email, next_url, 429)
    except MailError:
        if not admin.totp_enabled:
            session.pop(PENDING_KEY, None)
            return _login_error(t("auth.login.mail_failed"), admin.email, next_url)
        flash(t("auth.login.mail_failed_totp"), "warning")
        session[PENDING_KEY]["method"] = "totp"
        session.modified = True
    session[PENDING_KEY]["next"] = next_url
    session.modified = True
    return redirect(url_for("evrima_auth.verify"))


def _new_challenge(admin: Administrator) -> None:
    """Replace any open challenge with a new PIN and send it.

    Raises TooManyChallenges over the hourly limit, MailError when sending fails.
    """
    recent = db.session.scalar(
        select(func.count()).select_from(LoginChallenge)
        .where(LoginChallenge.administrator_id == admin.id,
               LoginChallenge.created_at > utcnow() - timedelta(hours=1)))
    if recent >= CHALLENGES_PER_HOUR:
        raise TooManyChallenges
    db.session.execute(
        update(LoginChallenge)
        .where(LoginChallenge.administrator_id == admin.id, LoginChallenge.used_at.is_(None))
        .values(used_at=utcnow()))
    challenge = LoginChallenge(
        administrator_id=admin.id, pin_hash="", expires_at=utcnow() + PIN_LIFETIME)
    db.session.add(challenge)
    db.session.flush()           # assigns the id the PIN hash is bound to
    pin = credentials.new_pin()
    challenge.pin_hash = credentials.pin_hash(challenge.id, pin)
    db.session.commit()
    session[PENDING_KEY] = {"admin_id": admin.id, "challenge_id": challenge.id, "method": "pin"}
    emails.send_pin(admin, pin)


# --- Step 2: PIN or TOTP code -------------------------------------------------------

@bp.route("/login/verify", methods=["GET", "POST"])
@limiter.limit("30 per minute", methods=["POST"])
def verify():
    """The e-mailed PIN, or a TOTP code for users who set up an authenticator app."""
    admin, challenge, pending = _pending_login()
    if admin is None:
        flash(t("auth.login.expired"), "warning")
        return redirect(url_for("evrima_auth.login"))

    method = request.values.get("method", pending.get("method", "pin"))
    if method != "totp" or not admin.totp_enabled:
        method = "pin"
    if request.method == "GET":
        return _verify_page(admin, method)

    until = lockout.locked_until(admin.email)
    if until is not None:
        minutes = max(1, int((until - utcnow()).total_seconds() // 60) + 1)
        return _verify_page(admin, method, t("auth.login.locked", minutes=minutes), 429)

    code = "".join(request.form.get("code", "").split())
    if challenge.attempts >= PIN_ATTEMPTS:
        return _verify_page(admin, method, t("auth.verify.too_many"))
    if method == "totp":
        return _check_totp(admin, challenge, code, pending)
    return _check_pin(admin, challenge, code, pending)


def _pending_login() -> tuple[Administrator | None, LoginChallenge | None, dict]:
    """The administrator and challenge of this browser's pending login.

    The pending login is valid only while its challenge is open: unused and
    younger than 10 minutes. A password change closes open challenges
    (sessions.end_all), so a cookie from before the change stops working.
    """
    pending = session.get(PENDING_KEY) or {}
    challenge = db.session.get(LoginChallenge, pending.get("challenge_id") or 0)
    if (challenge is None or challenge.administrator_id != pending.get("admin_id")
            or challenge.used_at is not None or challenge.expires_at <= utcnow()):
        session.pop(PENDING_KEY, None)
        return None, None, {}
    return db.session.get(Administrator, challenge.administrator_id), challenge, pending


def _verify_page(admin: Administrator, method: str, error: str | None = None, status: int = 200):
    """Render the verification form for `method`."""
    return render_template(
        "evrima/admin/auth/verify.html", admin=admin, method=method, error=error), status


def _check_pin(admin: Administrator, challenge: LoginChallenge, code: str, pending: dict):
    """Accept the challenge's PIN; count everything else as a failure."""
    if code.isdecimal() and credentials.same(
            challenge.pin_hash, credentials.pin_hash(challenge.id, code)):
        challenge.used_at = utcnow()
        db.session.commit()
        return _finish_login(admin, pending.get("next"), via="pin")
    return _wrong_code(admin, challenge, "pin")


def _check_totp(admin: Administrator, challenge: LoginChallenge, code: str, pending: dict):
    """Accept a valid TOTP code that has not been used before."""
    secret = totp.decrypt(admin.totp_secret)
    step = totp.matching_step(secret, code, admin.totp_last_step) if secret else None
    if step is None:
        return _wrong_code(admin, challenge, "totp")
    admin.totp_last_step = step
    challenge.used_at = utcnow()
    db.session.commit()
    return _finish_login(admin, pending.get("next"), via="totp")


def _wrong_code(admin: Administrator, challenge: LoginChallenge, method: str):
    """Count a wrong code on the challenge and in the lockout, then show the form again."""
    challenge.attempts += 1
    db.session.commit()
    lockout.record_failure(admin.email)
    audit.record(f"login.{method}_failed", admin=admin)
    exhausted = challenge.attempts >= PIN_ATTEMPTS
    return _verify_page(admin, method, t("auth.verify.too_many" if exhausted else "auth.verify.wrong"))


@bp.post("/login/resend")
@limiter.limit("5 per 15 minutes")
def resend():
    """Send a new PIN; the previous one stops working."""
    admin, _, pending = _pending_login()
    if admin is None:
        flash(t("auth.login.expired"), "warning")
        return redirect(url_for("evrima_auth.login"))
    next_url = pending.get("next")
    try:
        _new_challenge(admin)
        flash(t("auth.verify.resent"), "info")
    except TooManyChallenges:
        audit.record("login.too_many_codes", admin=admin)
        flash(t("auth.login.too_many_codes"), "danger")
    except MailError:
        flash(t("auth.login.mail_failed"), "danger")
    session[PENDING_KEY]["next"] = next_url
    session.modified = True
    return redirect(url_for("evrima_auth.verify"))


def _finish_login(admin: Administrator, next_url: str | None, via: str) -> Response:
    """Log in: session cookie, trusted device after a code, the user's language, audit."""
    session.pop(PENDING_KEY, None)
    lockout.clear(admin.email)
    i18n.set_language(admin.language)
    response = redirect(safe_next(next_url))
    sessions.start_session(response, admin)
    if via in ("pin", "totp"):
        sessions.remember_device(response, admin)
    audit.record("login", admin=admin, detail=via)
    if via == "totp":
        try:
            emails.send_totp_login_notice(admin)
        except MailError:
            pass    # the notice is a courtesy; failing it must not block the login
    return response


@bp.post("/logout")
def logout():
    """Log this browser out. The trusted-device cookie stays, as it is meant to."""
    admin = sessions.current_admin()
    response = redirect(url_for("evrima_auth.login"))
    sessions.end_session(response)
    if admin is not None:
        audit.record("logout", admin=admin)
    flash(t("auth.logout.done"), "info")
    return response


# --- Forgotten password, invitations ------------------------------------------------

@bp.route("/password/forgot", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes", methods=["POST"])
def forgot_password():
    """Send a reset link. The answer is the same whether the e-mail exists or not."""
    if request.method == "POST":
        email = normalise_email(request.form.get("email"))
        admin = db.session.scalar(select(Administrator).where(Administrator.email == email))
        if admin is not None:
            token = create_link(admin, "reset", RESET_LIFETIME)
            audit.record("password.reset_requested", admin=admin)
            try:
                emails.send_reset(admin, token)
            except MailError:
                pass    # same answer either way; the error is in the log
        flash(t("auth.forgot.sent"), "info")
        return redirect(url_for("evrima_auth.login"))
    return render_template("evrima/admin/auth/forgot.html")


def create_link(admin: Administrator, purpose: str, lifetime: timedelta) -> str:
    """Create a one-time link token; older unused links of the same purpose stop working."""
    db.session.execute(
        update(AccountLink)
        .where(AccountLink.administrator_id == admin.id, AccountLink.purpose == purpose,
               AccountLink.used_at.is_(None))
        .values(used_at=utcnow()))
    token = credentials.new_token()
    db.session.add(AccountLink(
        token_hash=credentials.token_hash(token), administrator_id=admin.id,
        purpose=purpose, expires_at=utcnow() + lifetime))
    db.session.commit()
    return token


@bp.route("/password/set/<token>", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", methods=["POST"])
def set_password(token: str):
    """Choose a password from a reset or invitation link. Ends every existing session."""
    link = db.session.scalar(
        select(AccountLink).where(AccountLink.token_hash == credentials.token_hash(token)))
    if link is None or link.used_at is not None or link.expires_at < utcnow():
        flash(t("auth.set_password.invalid_link"), "danger")
        return redirect(url_for("evrima_auth.login"))
    admin = db.session.get(Administrator, link.administrator_id)

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        problem = credentials.password_problem(password)
        if problem:
            error = t(problem)
        elif password != request.form.get("confirm", ""):
            error = t("auth.password.mismatch")
        else:
            admin.password_hash = credentials.hash_password(password)
            admin.password_changed_at = utcnow()
            link.used_at = utcnow()
            db.session.commit()
            sessions.end_all(admin)
            audit.record("invite.accepted" if link.purpose == "invite" else "password.reset", admin=admin)
            flash(t("auth.set_password.done"), "success")
            return redirect(url_for("evrima_auth.login"))
    return render_template(
        "evrima/admin/auth/set_password.html", admin=admin, invite=link.purpose == "invite",
        error=error)
