"""Declarative base, shared column mixins, and portable column types for
all ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base. Import this, not `sqlalchemy.orm.DeclarativeBase`,
    so Alembic's autogenerate sees every model registered against one metadata."""


# JSONB on Postgres (production/dev), generic JSON everywhere else — lets
# unit tests build these tables against an in-memory SQLite engine (see
# ingestion/tests/test_pipeline.py, backend/tests/conftest.py) without
# hitting SQLite's "can't render element of type JSONB" compile error,
# while production keeps JSONB's indexing/operator advantages unchanged.
PortableJSON = JSON().with_variant(JSONB, "postgresql")


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
