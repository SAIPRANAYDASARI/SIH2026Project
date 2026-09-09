"""Request/response contracts for licence verification and gap analysis
(Step 9).
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.verification import LicenceStatus, LicenceType


class VerifyRequest(BaseModel):
    licence_number: str = Field(min_length=1, max_length=64)
    licence_type: LicenceType | None = None


class VerifyResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    licence_number: str
    licence_type: LicenceType
    status: LicenceStatus
    holder_name: str | None = None
    is_number: str | None = None
    product_category: str | None = None
    valid_from: datetime.date | None = None
    valid_until: datetime.date | None = None
    is_seed_data: bool


class VerifyResponse(BaseModel):
    found: bool
    result: VerifyResult | None = None
    message: str


class GapCheckRequest(BaseModel):
    product_description: str = Field(min_length=1, max_length=1000)
    held_licence_numbers: list[str] = Field(default_factory=list)


class MissingScheme(BaseModel):
    code: str
    name: str
    mandatory: bool
    reason: str


class GapCheckResponse(BaseModel):
    matched_scheme_codes: list[str]
    missing_mandatory: list[MissingScheme]
    missing_voluntary: list[MissingScheme]
    covered_scheme_codes: list[str]
    disclaimer: str
