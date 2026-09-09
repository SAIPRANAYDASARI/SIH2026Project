"""Certification scheme reference data.

`rules_yaml_path` points at the deterministic YAML lookup table (fees,
timelines, eligibility — see docs/DECISIONS.md decision #2) that the rules
engine reads at request time in Step 8. The LLM may quote these values
verbatim; it must never author them, and this table is what the citation
validator checks fee/timeline claims against.
"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Scheme(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "schemes"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    # e.g. ISI_SCHEME_I, CRS, FMCS, HALLMARKING, ECO_MARK
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_yaml_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
