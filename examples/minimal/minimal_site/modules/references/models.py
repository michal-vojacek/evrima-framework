"""Database model of a client reference (the example module of docs/modules.md)."""

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from evrima.db import Base, utcnow
from evrima.media.models import MediaFile


class Reference(Base):
    """One completed project shown on the website.

    A reference may be published only with the client's consent: the day it
    was given and how it is documented. The database refuses a published
    reference without a consent date, so no code path can skip the rule.
    """

    __tablename__ = "references_items"
    __table_args__ = (
        CheckConstraint("NOT published OR consent_on IS NOT NULL", name="published_needs_consent"),
        {"info": {"evrima_module": "references"}},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200))
    website_url: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")     # cleaned HTML (evrima.editor)
    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("evrima_media.id", ondelete="SET NULL"))
    consent_on: Mapped[date | None]                                  # the day the client agreed
    consent_proof: Mapped[str] = mapped_column(String(500), default="")  # e.g. "e-mail of 3 Oct 2026"
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    # Lower comes first on the website; new references start at the top.
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    image: Mapped[MediaFile | None] = relationship(lazy="joined")
