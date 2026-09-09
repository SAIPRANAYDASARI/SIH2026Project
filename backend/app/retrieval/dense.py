"""Dense retrieval via pgvector cosine similarity.

Like `sparse.py`, this needs a real Postgres+pgvector database
(`Chunk.embedding.cosine_distance(...)` compiles to the `<=>` operator,
which the ivfflat index from migration `0001_initial_schema.py` accelerates)
and so is exercised via `app/retrieval/cli.py`, not a unit test.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk


class DenseRetriever(Protocol):
    async def search(
        self, session: AsyncSession, query_vector: list[float], limit: int
    ) -> list[tuple[uuid.UUID, float]]:
        """Returns (chunk_id, similarity_score) pairs ordered by descending
        similarity — cosine *distance* ascending, converted to a
        1 - distance similarity score for the transparency breakdown."""
        ...


class PgVectorRetriever:
    async def search(
        self, session: AsyncSession, query_vector: list[float], limit: int
    ) -> list[tuple[uuid.UUID, float]]:
        distance = Chunk.embedding.cosine_distance(query_vector)
        stmt = (
            select(Chunk.id, distance.label("distance"))
            .where(Chunk.embedding.is_not(None))
            .order_by(distance.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        return [(row.id, 1.0 - float(row.distance)) for row in rows]
