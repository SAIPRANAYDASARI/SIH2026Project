"""Indian Standards catalogue metadata.

Only metadata — title, scope, technical committee, ICS code, amendment and
reaffirmation status — is stored. Full IS text is copyrighted by BIS and is
never ingested; see docs/DATA_SOURCES.md.
"""

from __future__ import annotations

from sqlalchemy import ARRAY, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Standard(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "standards"

    is_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    technical_committee: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ics_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(nullable=True)
    amendment_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reaffirmation_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_qco_mandatory: Mapped[bool] = mapped_column(default=False, nullable=False)
    applicable_schemes: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)), nullable=True)

    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
