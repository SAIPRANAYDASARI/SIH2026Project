"""BM25-style sparse retrieval via Postgres full-text search.

Uses the `manak_search` configuration (migration `0002_search_config.py`,
no stemming) rather than `english`, and `ts_rank_cd` (cover density —
rewards matched terms appearing close together, which suits short technical
queries better than plain `ts_rank`).

This talks to a real Postgres database (`to_tsvector`/`plainto_tsquery`/
`ts_rank_cd` have no SQLite equivalent), so it's exercised by
`app/retrieval/cli.py` against a live database, not by a unit test — see
`tests/retrieval/test_hybrid.py`'s docstring for how the fusion/orchestration
logic around this is still tested without one.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk

SEARCH_CONFIG = "manak_search"


class SparseRetriever(Protocol):
    async def search(
        self, session: AsyncSession, query_text: str, limit: int
    ) -> list[tuple[uuid.UUID, float]]:
        """Returns (chunk_id, score) pairs ordered by descending score."""
        ...


class PostgresFTSRetriever:
    async def search(
        self, session: AsyncSession, query_text: str, limit: int
    ) -> list[tuple[uuid.UUID, float]]:
        tsvector = func.to_tsvector(SEARCH_CONFIG, Chunk.text_content)
        tsquery = func.plainto_tsquery(SEARCH_CONFIG, query_text)
        score = func.ts_rank_cd(tsvector, tsquery).label("score")

        stmt = (
            select(Chunk.id, score)
            .where(tsvector.op("@@")(tsquery))
            .order_by(score.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
        return [(row.id, float(row.score)) for row in rows]
