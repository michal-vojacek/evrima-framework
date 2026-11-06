"""Public pages of the admin login: login, logout, forgotten password.

Login is e-mail and password, nothing else (decided by Michal 2026-11-06: the
e-mailed PIN, trusted devices and TOTP were removed; the admin holds no
personal data of visitors, and the database is backed up externally, so a
break-in is rolled back and the passwords changed). What limits guessing: the
password policy (at least 12 characters), Argon2id, 30 attempts a minute per
client and the lockout per e-mail and client (10 failures, 40 minutes, kept
in the database). Error messages never reveal whether an e-mail belongs to an
administrator.
"""

import re
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import select, update
from werkzeug.wrappers.response import Response

from evrima import i18n
from evrima.admin.navigation import safe_next
from evrima.auth import audit, credentials, emails, lockout, sessions
from evrima.auth.models import AccountLink, Administrator
from evrima.db import db, utcnow
from evrima.i18n import translate as t
from evrima.mail import MailError
from evrima.security import limiter

bp = Blueprint("evrima_auth", __name__, url_prefix="/admin")

RESET_LIFETIME = timedelta(hours=1)
INVITE_LIFETIME = timedelta(days=3)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalise_email(value: str | None) -> str:
    """Trim and lower-case an e-mail; addresses are compared case-insensitively."""
    return (value or "").strip().lower()[:254]


# --- Login and logout -------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("30 per minute", methods=["POST"])
def login():
    """E-mail and password."""
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

    lockout.clear(email)
    i18n.set_language(admin.language)
    response = redirect(next_url)
    sessions.start_session(response, admin)
    audit.record("login", admin=admin)
    return response


def _login_error(message: str, email: str, next_url: str, status: int = 200):
    """Show the login form again with an error and the e-mail filled in."""
    return render_template(
        "evrima/admin/auth/login.html", error=message, email=email, next=next_url), status


@bp.post("/logout")
def logout():
    """Log this browser out."""
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
