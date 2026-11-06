"""Temporary lockout after repeated failed logins.

After 10 wrong passwords for the same e-mail
from the same IP address (an IPv6 /64 counts as one address), logging in is blocked for 40 minutes counted from
the last failure. Counting per e-mail *and* IP means a stranger who knows the
e-mail cannot lock the real owner out (docs/framework.md, decided 2026-10-14).
The counters live in the database, not in Redis.
"""

import hashlib
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import select

from evrima.auth.models import LoginFailure
from evrima.db import db, utcnow
from evrima.security import client_key

MAX_FAILURES = 10
LOCKOUT = timedelta(minutes=40)


def _key(email: str) -> str:
    """A hash of e-mail and client IP; the table keeps no readable addresses."""
    secret = current_app.config["SECRET_KEY"]
    raw = f"{secret}|{email.strip().lower()}|{client_key()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def locked_until(email: str) -> datetime | None:
    """When the lockout for this e-mail and IP ends, or None if not locked."""
    record = db.session.scalar(select(LoginFailure).where(LoginFailure.key == _key(email)))
    if record is None or record.count < MAX_FAILURES:
        return None
    until = record.last_failed_at + LOCKOUT
    return until if until > utcnow() else None


def record_failure(email: str) -> None:
    """Count one failed attempt. A lockout that has run out starts counting from zero."""
    key = _key(email)
    now = utcnow()
    record = db.session.scalar(select(LoginFailure).where(LoginFailure.key == key))
    if record is None:
        record = LoginFailure(key=key, count=0, last_failed_at=now)
        db.session.add(record)
    elif now - record.last_failed_at > LOCKOUT:
        record.count = 0
    record.count += 1
    record.last_failed_at = now
    db.session.commit()


def clear(email: str) -> None:
    """Forget the failures after a successful login."""
    record = db.session.scalar(select(LoginFailure).where(LoginFailure.key == _key(email)))
    if record is not None:
        db.session.delete(record)
        db.session.commit()
