"""Licence records for mark verification (F4): CM/L, CRS R-numbers, HUIDs."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Date, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LicenceType(StrEnum):
    CML = "cml"  # ISI Scheme CM/L licence
    CRS_R = "crs_r"  # Compulsory Registration Scheme R-number
    HUID = "huid"  # Hallmarking Unique ID


class LicenceStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    NOT_FOUND = "not_found"


class Licence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "licences"

    licence_number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    licence_type: Mapped[LicenceType] = mapped_column(
        Enum(LicenceType, name="licence_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    status: Mapped[LicenceStatus] = mapped_column(
        Enum(LicenceStatus, name="licence_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    holder_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    valid_from: Mapped[Date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[Date | None] = mapped_column(Date, nullable=True)
    is_seed_data: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = ()
