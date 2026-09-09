"""custom non-stemming text search configuration for chunks.text_content

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

Replaces the Step-1 'english' full-text index with one built on a custom
`manak_search` configuration copied from `pg_catalog.simple`. `simple`
performs no stemming — 'english' would, e.g., collapsing "requirements" to
"requir" — which matters here because BIS/QCO text is full of exact
identifiers and technical terms (IS numbers, clause references, scheme
names) where stemming only risks distorting a match, not improving recall.

This does not, by itself, make a compound token like "CM/L 1234567" or
"IS 15111" survive as a single search token — Postgres's default parser
still splits on punctuation before any dictionary sees it. Query-time exact
identifier matching (IS numbers, clause references, CM/L numbers, HUIDs)
is therefore handled by the query router's dedicated regex/lookup path in
Step 4, not by full-text search alone. See docs/DECISIONS.md.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.execute("CREATE TEXT SEARCH CONFIGURATION manak_search (COPY = pg_catalog.simple)")
    op.execute("DROP INDEX IF EXISTS ix_chunks_text_fts")
    op.execute(
        "CREATE INDEX ix_chunks_text_fts ON chunks "
        "USING GIN (to_tsvector('manak_search', text_content))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_text_fts")
    op.execute(
        "CREATE INDEX ix_chunks_text_fts ON chunks "
        "USING GIN (to_tsvector('english', text_content))"
    )
    op.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS manak_search")
