"""Exact-identifier lookup, tried before fuzzy hybrid search.

Per the brief: "Query understanding must detect and preserve exact
identifiers ... and route them to exact-match lookup first." This module
handles the two identifier types that map onto retrievable *chunks* — IS
numbers and clause references. CM/L numbers, CRS R-numbers and HUIDs are
licence identifiers (they identify a `Licence` row, not a `Chunk`); routing
those is the mark-verification endpoint's job (Step 9,
`POST /api/v1/verify/licence`), not this retrieval core — see
`docs/DECISIONS.md`.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk
from app.retrieval.query_understanding import Identifier, IdentifierType

_CHUNK_ROUTABLE_TYPES = frozenset({IdentifierType.IS_NUMBER, IdentifierType.CLAUSE_REFERENCE})


class ExactMatchRetriever(Protocol):
    async def search(
        self, session: AsyncSession, identifiers: list[Identifier], limit: int
    ) -> list[uuid.UUID]: ...


class ChunkExactMatchRetriever:
    async def search(
        self, session: AsyncSession, identifiers: list[Identifier], limit: int
    ) -> list[uuid.UUID]:
        is_numbers = [i.value for i in identifiers if i.type is IdentifierType.IS_NUMBER]
        clauses = [i.value for i in identifiers if i.type is IdentifierType.CLAUSE_REFERENCE]

        if not is_numbers and not clauses:
            return []

        if is_numbers and clauses:
            # Prefer the IS-number + clause-number intersection when both
            # are present in the query — falls through to a bare IS-number
            # (or clause-only) match below if the intersection is empty.
            precise_stmt = (
                select(Chunk.id)
                .where(Chunk.is_number.in_(is_numbers), Chunk.clause_number.in_(clauses))
                .limit(limit)
            )
            precise_ids = list((await session.execute(precise_stmt)).scalars())
            if precise_ids:
                return precise_ids

        if is_numbers:
            fallback_stmt = select(Chunk.id).where(Chunk.is_number.in_(is_numbers)).limit(limit)
        else:
            fallback_stmt = select(Chunk.id).where(Chunk.clause_number.in_(clauses)).limit(limit)

        return list((await session.execute(fallback_stmt)).scalars())


def has_chunk_routable_identifier(identifiers: list[Identifier]) -> bool:
    return any(i.type in _CHUNK_ROUTABLE_TYPES for i in identifiers)
