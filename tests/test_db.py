"""Request-scoped database sessions."""

from flask import g
from sqlalchemy import text

from evrima.db import db


def test_session_is_shared_within_one_app_context(app):
    with app.app_context():
        assert db.session is db.session
        assert db.session.execute(text("SELECT 1")).scalar() == 1


def test_session_is_closed_when_the_context_ends(app):
    with app.app_context():
        session = db.session
        session.execute(text("SELECT 1"))
    with app.app_context():
        assert "evrima_db_session" not in g
        assert db.session is not session


def test_each_app_has_its_own_engine(make_app, tmp_path):
    first = make_app()
    second = make_app(env={"DATABASE_URL": f"sqlite:///{(tmp_path / 'b.db').as_posix()}"})
    with first.app_context():
        first_engine = db.engine
    with second.app_context():
        assert db.engine is not first_engine
