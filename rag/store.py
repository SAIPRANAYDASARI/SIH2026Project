"""Index storage: SQLite (FTS5/BM25) for keyword search, a NumPy matrix for
dense vectors.

This replaces Postgres+pgvector because the target machine has no Docker and
no database server. At this corpus size that is not a compromise: SQLite's
FTS5 gives real BM25 ranking, and ~30k vectors x 1024 dims is ~120MB of
float32 that brute-force cosine scans in a few milliseconds — exact search,
with none of the recall loss an approximate index would introduce.

Vectors live in a .npy file rather than as SQLite blobs so the whole matrix
can be memory-mapped and scored in one vectorised operation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rag import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    sha256       TEXT PRIMARY KEY,
    relpath      TEXT NOT NULL,
    filename     TEXT NOT NULL,
    title        TEXT NOT NULL,
    category     TEXT NOT NULL,
    subcategory  TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    page_count   INTEGER NOT NULL,
    pages_ok     INTEGER NOT NULL,
    pages_scanned INTEGER NOT NULL,
    pages_corrupt INTEGER NOT NULL,
    source_url   TEXT,
    error        TEXT,
    page_report  TEXT NOT NULL DEFAULT '{}',
    -- Other paths holding a byte-identical copy of this document. Indexed
    -- once, but the duplicate locations are kept so provenance is not lost.
    duplicate_paths TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY,
    doc_sha      TEXT NOT NULL REFERENCES documents(sha256),
    relpath      TEXT NOT NULL,
    page_number  INTEGER NOT NULL,
    ordinal      INTEGER NOT NULL,
    text         TEXT NOT NULL,
    is_numbers   TEXT NOT NULL DEFAULT '',
    gazette_refs TEXT NOT NULL DEFAULT '',
    vector_row   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_sha);
CREATE INDEX IF NOT EXISTS idx_chunks_vec ON chunks(vector_row);

-- Keyword search. 'unicode61' with remove_diacritics=2 keeps Devanagari
-- intact while folding Latin case/accents.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    is_numbers,
    gazette_refs,
    title,
    content='',
    tokenize="unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- HSN import/export compliance matrix. A lookup table, not prose to embed:
-- almost every question against it is an exact code ("what documents for
-- HSN 1011010?") or a product-name search, both of which a plain index
-- answers exactly rather than by similarity. See rag/hsn.py.
CREATE TABLE IF NOT EXISTS hsn_codes (
    id                       INTEGER PRIMARY KEY,
    hsn_cd                   TEXT NOT NULL,
    level                    TEXT NOT NULL,
    chapter                  TEXT,
    chapter_title            TEXT,
    heading                  TEXT,
    product                  TEXT NOT NULL,
    import_core_docs         TEXT,
    import_bis_is            TEXT,
    import_dgft_policy       TEXT,
    import_licence_required  TEXT,
    import_monitoring_system TEXT,
    import_coo               TEXT,
    import_other_noc         TEXT,
    export_core_docs         TEXT,
    export_dgft_policy       TEXT,
    export_other_noc         TEXT,
    primary_regulator        TEXT,
    verify_against           TEXT
);
CREATE INDEX IF NOT EXISTS idx_hsn_code ON hsn_codes(hsn_cd);

CREATE VIRTUAL TABLE IF NOT EXISTS hsn_fts USING fts5(
    product,
    chapter_title,
    heading,
    content='hsn_codes',
    content_rowid='id',
    tokenize="unicode61 remove_diacritics 2"
);
"""


@dataclass
class ChunkRow:
    id: int
    relpath: str
    page_number: int
    text: str
    title: str
    category: str
    is_numbers: str
    source_url: str | None


def connect(path: Path = config.DB_PATH, *, create: bool = False) -> sqlite3.Connection:
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise FileNotFoundError(
            f"No index at {path}. Build it first:  python -m rag.cli build"
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    for stmt in (
        "DROP TABLE IF EXISTS chunks_fts",
        "DROP TABLE IF EXISTS chunks",
        "DROP TABLE IF EXISTS documents",
        "DROP TABLE IF EXISTS meta",
    ):
        conn.execute(stmt)
    conn.commit()
    init_schema(conn)


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def fetch_chunks(conn: sqlite3.Connection, ids: list[int]) -> dict[int, ChunkRow]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT c.id, c.relpath, c.page_number, c.text, c.is_numbers,
                   d.title, d.category, d.source_url
            FROM chunks c JOIN documents d ON d.sha256 = c.doc_sha
            WHERE c.id IN ({marks})""",
        ids,
    ).fetchall()
    return {
        r["id"]: ChunkRow(
            id=r["id"],
            relpath=r["relpath"],
            page_number=r["page_number"],
            text=r["text"],
            title=r["title"],
            category=r["category"],
            is_numbers=r["is_numbers"],
            source_url=r["source_url"],
        )
        for r in rows
    }


def save_vectors(matrix: np.ndarray, ids: np.ndarray) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(config.VECTORS_PATH, matrix.astype(np.float32))
    np.save(config.VECTOR_IDS_PATH, ids.astype(np.int64))


def load_vectors() -> tuple[np.ndarray, np.ndarray]:
    if not config.VECTORS_PATH.exists():
        raise FileNotFoundError(
            f"No vectors at {config.VECTORS_PATH}. Run:  python -m rag.cli build"
        )
    return (
        np.load(config.VECTORS_PATH, mmap_mode="r"),
        np.load(config.VECTOR_IDS_PATH),
    )
