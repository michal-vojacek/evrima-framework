"""Daily removal of login records that are no longer needed.

Failed logins are written with the e-mail that was typed and the client's IP
address, and bots against /admin/login write many of them. Personal data must
not be kept longer than its purpose needs (GDPR, data minimisation; indicative
only), and the tables would otherwise grow for ever (security audit
2026-11-06). Run daily by `flask evrima jobs`.

Kept for 30 days (decided by Michal 2026-11-06): audit entries of failed
logins, long enough to look into an attack noticed later. Removed as soon as
they are useless: lockout counters that ran out, expired reset and
invitation links and admin sessions. The audit
entries of administrators' own actions stay.
"""

from datetime import timedelta

from sqlalchemy import delete, or_

from evrima.auth import lockout, sessions
from evrima.auth.models import AccountLink, AdminSession, AuditEntry, LoginFailure
from evrima.db import db, utcnow

FAILED_LOGIN_RETENTION = timedelta(days=30)
FAILED_LOGIN_ACTIONS = ("login.failed", "login.pin_failed", "login.totp_failed", "login.too_many_codes")
# An expired link is kept one more day, so a person who clicks a
# day-old link still gets "expired" rather than "invalid".
EXPIRED_GRACE = timedelta(days=1)


def cleanup() -> int:
    """Delete the records described above; return how many rows went."""
    now = utcnow()
    statements = [
        delete(AuditEntry).where(AuditEntry.action.in_(FAILED_LOGIN_ACTIONS),
                                 AuditEntry.created_at < now - FAILED_LOGIN_RETENTION),
        delete(LoginFailure).where(LoginFailure.last_failed_at < now - lockout.LOCKOUT),
        delete(AccountLink).where(AccountLink.expires_at < now - EXPIRED_GRACE),
        delete(AdminSession).where(or_(AdminSession.last_seen_at < now - sessions.SESSION_IDLE,
                                       AdminSession.created_at < now - sessions.SESSION_MAX_AGE)),
    ]
    removed = sum(db.session.execute(statement).rowcount or 0 for statement in statements)
    db.session.commit()
    return removed
