"""Database access: SQLAlchemy engine, models base and request-scoped sessions.

Evrima uses plain SQLAlchemy rather than Flask-SQLAlchemy. The framework, its
modules and the website each keep their own Alembic migration branch, and plain
SQLAlchemy keeps that wiring explicit instead of hiding it behind an extension.

Usage in a view or module:

    from evrima.db import Base, db

    class Reference(Base):
        __tablename__ = "references"
        ...

    db.session.scalars(select(Reference)).all()
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from flask import Flask, current_app, g
from sqlalchemy import Engine, MetaData, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Deterministic constraint names. Without them PostgreSQL invents names, and an
# Alembic migration that later drops or alters a constraint cannot find it by
# name on another database.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_EXTENSION_KEY = "evrima.db"
_SESSION_KEY = "evrima_db_session"


class Base(DeclarativeBase):
    """Base class for every model of the framework, its modules and websites."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """The current time in UTC, without a time zone attached.

    Every timestamp in the database is naive UTC: SQLite (development, tests)
    drops time zones, and comparing aware with naive values raises errors.
    """
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class _State:
    """The engine and session factory bound to one Flask app."""

    engine: Engine
    session_factory: sessionmaker[Session]


class Database:
    """Gives views a SQLAlchemy session that lives for one app context.

    The state lives in `app.extensions`, not on this object, so one shared
    `db` instance serves any number of apps (every test builds its own).
    """

    def init_app(self, app: Flask) -> None:
        """Create the engine for `app` and close sessions after each request.

        Creating the engine does not connect, so a website starts even while
        the database is still booting; the health check reports it until then.
        """
        engine = create_engine(
            app.config["DATABASE_URL"],
            # Check a pooled connection before use. Costs a round trip, but a
            # database restart otherwise breaks the first request on every
            # stale connection in the pool.
            pool_pre_ping=True,
        )
        if engine.dialect.name == "sqlite":
            # SQLite ignores foreign keys unless asked per connection; without
            # this, ON DELETE CASCADE silently does nothing in development.
            event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        # expire_on_commit=False: objects stay readable after commit, e.g. when
        # a view commits and then renders the saved record.
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        app.extensions[_EXTENSION_KEY] = _State(engine, factory)
        app.teardown_appcontext(_close_session)

    @property
    def engine(self) -> Engine:
        """The engine of the current app."""
        return current_app.extensions[_EXTENSION_KEY].engine

    @property
    def session(self) -> Session:
        """The session of the current app context, created on first use."""
        if _SESSION_KEY not in g:
            g.evrima_db_session = current_app.extensions[_EXTENSION_KEY].session_factory()
        return g.evrima_db_session

    def ping(self) -> None:
        """Run a trivial query; raises if the database is unreachable."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    """Turn on foreign key enforcement for a new SQLite connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _close_session(_exc: BaseException | None) -> None:
    """Close the context's session, rolling back anything left uncommitted."""
    session = g.pop(_SESSION_KEY, None)
    if session is not None:
        session.close()


db = Database()
