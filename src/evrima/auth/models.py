"""Database models of the admin login (docs/framework.md, "Admin login").

Times are stored as naive UTC (`utcnow()`): SQLite, used in development and
tests, drops time zones, and mixing aware and naive values breaks comparisons.

Secrets are never stored as they are: passwords as Argon2id hashes, random
tokens (sessions, devices, links) as SHA-256, PINs as HMAC with the app's
SECRET_KEY, TOTP secrets encrypted.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evrima.db import Base, utcnow


class Administrator(Base):
    """A person who may log in to the admin. There is a single role."""

    __tablename__ = "evrima_administrators"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lower-case; the user cannot change it (only `flask evrima set-admin-email`).
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    # None until the invited person sets a password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(5), default="cs")
    totp_secret: Mapped[str | None] = mapped_column(Text)            # encrypted
    totp_pending_secret: Mapped[str | None] = mapped_column(Text)    # encrypted, during setup
    # The last accepted TOTP time step: a code is accepted only once.
    totp_last_step: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    password_changed_at: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]

    sessions: Mapped[list["AdminSession"]] = relationship(
        back_populates="administrator", cascade="all, delete-orphan", passive_deletes=True)
    devices: Mapped[list["TrustedDevice"]] = relationship(
        back_populates="administrator", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def is_invited(self) -> bool:
        """True until the person has set a password."""
        return self.password_hash is None

    @property
    def totp_enabled(self) -> bool:
        """True when a TOTP code may replace the e-mailed PIN."""
        return self.totp_secret is not None

    @property
    def display_name(self) -> str:
        """The name, or the e-mail when no name is set."""
        return self.name or self.email


class AdminSession(Base):
    """A logged-in browser. The cookie holds a random token, the table its hash."""

    __tablename__ = "evrima_admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    administrator_id: Mapped[int] = mapped_column(
        ForeignKey("evrima_administrators.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(200), default="")

    administrator: Mapped[Administrator] = relationship(back_populates="sessions")


class TrustedDevice(Base):
    """A browser that verified a PIN or TOTP code; no PIN is asked there for 10 days."""

    __tablename__ = "evrima_trusted_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    administrator_id: Mapped[int] = mapped_column(
        ForeignKey("evrima_administrators.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    user_agent: Mapped[str] = mapped_column(String(200), default="")

    administrator: Mapped[Administrator] = relationship(back_populates="devices")


class LoginChallenge(Base):
    """The second step of a login: an e-mailed PIN waiting to be entered."""

    __tablename__ = "evrima_login_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    administrator_id: Mapped[int] = mapped_column(
        ForeignKey("evrima_administrators.id", ondelete="CASCADE"), index=True)
    pin_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0)
    used_at: Mapped[datetime | None]


class LoginFailure(Base):
    """Failed attempts per e-mail and IP address, for the temporary lockout.

    The key is a hash of both, so the table holds no readable addresses.
    """

    __tablename__ = "evrima_login_failures"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    count: Mapped[int] = mapped_column(default=0)
    last_failed_at: Mapped[datetime] = mapped_column(default=utcnow)


class AccountLink(Base):
    """A one-time link sent by e-mail: a password reset or an invitation."""

    __tablename__ = "evrima_account_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    administrator_id: Mapped[int] = mapped_column(
        ForeignKey("evrima_administrators.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(10))       # "reset" or "invite"
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class AuditEntry(Base):
    """Who did what and when (docs/framework.md, "Security baseline").

    The e-mail is copied, not only referenced, so an entry stays readable
    after the administrator has been removed.
    """

    __tablename__ = "evrima_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    administrator_id: Mapped[int | None] = mapped_column(
        ForeignKey("evrima_administrators.id", ondelete="SET NULL"))
    email: Mapped[str] = mapped_column(String(254), default="")
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(45), default="")
