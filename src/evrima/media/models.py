"""Database record of an uploaded file (docs/framework.md, "Uploads and the rich-text editor")."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from evrima.db import Base, utcnow


class MediaFile(Base):
    """One uploaded file: an image (with its size variants) or a document.

    `stored_name` is random and never derived from the uploaded name, which is
    kept only for display (`original_name`). A file is "claimed" once a module
    saves a form that uses it; unclaimed files are removed by the cleanup.
    """

    __tablename__ = "evrima_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))             # "image" or "document"
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)
    extension: Mapped[str] = mapped_column(String(8))          # of the stored original
    content_type: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str] = mapped_column(String(255), default="")
    size: Mapped[int] = mapped_column(Integer)                 # bytes, stored original
    width: Mapped[int | None]
    height: Mapped[int | None]
    # Widths of the generated variants, e.g. "480,960,1600".
    variants: Mapped[str] = mapped_column(String(64), default="")
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("evrima_administrators.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    claimed_at: Mapped[datetime | None]

    @property
    def variant_widths(self) -> list[int]:
        """The widths of the generated variants, smallest first."""
        return [int(width) for width in self.variants.split(",") if width]

    @property
    def filename(self) -> str:
        """Name of the stored original on disk."""
        return f"{self.stored_name}.{self.extension}"
