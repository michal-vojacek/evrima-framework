"""Daily cleanup of login records (evrima.auth.cleanup)."""

from datetime import timedelta

from sqlalchemy import func, select

from conftest import add_admin
from evrima.auth import cleanup
from evrima.auth.models import AccountLink, AdminSession, AuditEntry, LoginFailure
from evrima.db import db, utcnow


def count(model):
    return db.session.scalar(select(func.count()).select_from(model))


def test_old_failed_logins_and_expired_records_go_the_rest_stays(app):
    admin_id = add_admin(app)
    now = utcnow()
    with app.app_context():
        db.session.add_all([
            AuditEntry(action="login.failed", email="bot@example.com", ip="203.0.113.9", created_at=now - timedelta(days=31)),
            AuditEntry(action="login.failed", email="bot@example.com", ip="203.0.113.9", created_at=now - timedelta(days=29)),
            AuditEntry(action="login.too_many_codes", created_at=now - timedelta(days=40)),
            AuditEntry(action="admin.invited", administrator_id=admin_id, created_at=now - timedelta(days=400)),
            LoginFailure(key="a" * 64, count=3, last_failed_at=now - timedelta(hours=1)),
            LoginFailure(key="b" * 64, count=9, last_failed_at=now - timedelta(minutes=5)),
            AccountLink(administrator_id=admin_id, purpose="reset", token_hash="c" * 64, expires_at=now - timedelta(days=2)),
            AccountLink(administrator_id=admin_id, purpose="invite", token_hash="d" * 64, expires_at=now + timedelta(days=1)),
            AdminSession(administrator_id=admin_id, token_hash="e" * 64, last_seen_at=now - timedelta(hours=3)),
            AdminSession(administrator_id=admin_id, token_hash="f" * 64, last_seen_at=now),
        ])
        db.session.commit()
        assert cleanup.cleanup() == 5
        assert sorted(e.action for e in db.session.scalars(select(AuditEntry))) == ["admin.invited", "login.failed"]
        assert [f.key[0] for f in db.session.scalars(select(LoginFailure))] == ["b"]
        assert count(AccountLink) == 1
        assert count(AdminSession) == 1
