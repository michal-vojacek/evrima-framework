"""Logged-in browsers and trusted devices, both kept on the server.

Two cookies, both limited to /admin, HttpOnly, and Secure outside development:

- `evrima_admin`: the login session. Ends after 2 hours of inactivity and
  after 24 hours at most (docs/framework.md, decided 2026-10-14). Stored on
  the server, so it can be ended remotely (logout everywhere, password change).
- `evrima_device`: a trusted device. After a verified PIN or TOTP code, the
  browser needs no PIN for 10 days. SameSite=Strict: it is never sent along
  with a request started on another website.

Flask's own session cookie keeps only harmless state (language, flash
messages, the CSRF token, the pending login step).
"""

from datetime import timedelta

from flask import current_app, g, request
from sqlalchemy import delete, select, update
from werkzeug.wrappers.response import Response

from evrima.auth import credentials
from evrima.auth.models import AdminSession, Administrator, LoginChallenge, TrustedDevice
from evrima.db import db, utcnow

SESSION_COOKIE = "evrima_admin"
DEVICE_COOKIE = "evrima_device"
COOKIE_PATH = "/admin"

SESSION_IDLE = timedelta(hours=2)
SESSION_MAX_AGE = timedelta(hours=24)
DEVICE_LIFETIME = timedelta(days=10)
# last_seen_at is written at most this often, not on every click.
TOUCH_INTERVAL = timedelta(minutes=1)


def current_admin() -> Administrator | None:
    """The administrator of this request, or None. Loaded once per request."""
    if "evrima_admin" not in g:
        g.evrima_admin = _load_session()
    return g.evrima_admin


def _load_session() -> Administrator | None:
    """Find the session behind the cookie and enforce both time limits."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    record = db.session.scalar(
        select(AdminSession).where(AdminSession.token_hash == credentials.token_hash(token)))
    if record is None:
        return None
    now = utcnow()
    if now - record.last_seen_at > SESSION_IDLE or now - record.created_at > SESSION_MAX_AGE:
        db.session.delete(record)
        db.session.commit()
        return None
    if now - record.last_seen_at > TOUCH_INTERVAL:
        record.last_seen_at = now
        db.session.commit()
    return record.administrator


def start_session(response: Response, admin: Administrator) -> None:
    """Log `admin` in on this browser: a new session row and its cookie.

    Expired sessions and devices of the same administrator are removed on the
    way, so the tables do not grow forever.
    """
    now = utcnow()
    db.session.execute(delete(AdminSession).where(
        AdminSession.administrator_id == admin.id, AdminSession.created_at < now - SESSION_MAX_AGE))
    db.session.execute(delete(TrustedDevice).where(
        TrustedDevice.administrator_id == admin.id, TrustedDevice.expires_at < now))
    token = credentials.new_token()
    db.session.add(AdminSession(
        token_hash=credentials.token_hash(token), administrator_id=admin.id,
        user_agent=_user_agent()))
    admin.last_login_at = utcnow()
    db.session.commit()
    g.evrima_admin = admin
    _set_cookie(response, SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, samesite="Lax")


def end_session(response: Response) -> None:
    """Log this browser out."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.session.execute(
            delete(AdminSession).where(AdminSession.token_hash == credentials.token_hash(token)))
        db.session.commit()
    response.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH)
    g.evrima_admin = None


def end_all(admin: Administrator) -> None:
    """End every session, pending login and trusted device of `admin` (e.g. after a password change).

    Closing the open challenges matters: a pending login only needs its
    challenge, so without this a browser that knew the old password could
    still finish logging in with a code.
    """
    db.session.execute(delete(AdminSession).where(AdminSession.administrator_id == admin.id))
    db.session.execute(
        update(LoginChallenge)
        .where(LoginChallenge.administrator_id == admin.id, LoginChallenge.used_at.is_(None))
        .values(used_at=utcnow()))
    db.session.execute(delete(TrustedDevice).where(TrustedDevice.administrator_id == admin.id))
    db.session.commit()


def trusted_device(admin: Administrator) -> TrustedDevice | None:
    """The valid trusted device of `admin` behind this browser's cookie, if any."""
    token = request.cookies.get(DEVICE_COOKIE)
    if not token:
        return None
    device = db.session.scalar(
        select(TrustedDevice).where(TrustedDevice.token_hash == credentials.token_hash(token)))
    if device is None or device.administrator_id != admin.id or device.expires_at < utcnow():
        return None
    device.last_used_at = utcnow()
    db.session.commit()
    return device


def remember_device(response: Response, admin: Administrator) -> None:
    """Trust this browser for `admin` for the next 10 days."""
    token = credentials.new_token()
    db.session.add(TrustedDevice(
        token_hash=credentials.token_hash(token), administrator_id=admin.id,
        expires_at=utcnow() + DEVICE_LIFETIME, user_agent=_user_agent()))
    db.session.commit()
    _set_cookie(response, DEVICE_COOKIE, token, max_age=DEVICE_LIFETIME, samesite="Strict")


def _set_cookie(response: Response, name: str, value: str, max_age: timedelta, samesite: str) -> None:
    """Set an admin cookie with the framework's security flags."""
    response.set_cookie(
        name, value, max_age=int(max_age.total_seconds()), path=COOKIE_PATH,
        secure=current_app.config["SESSION_COOKIE_SECURE"], httponly=True, samesite=samesite)


def _user_agent() -> str:
    """A short description of the browser, shown in the list of devices."""
    return (request.user_agent.string or "")[:200]


