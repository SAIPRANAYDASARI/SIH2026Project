"""Three retrieval modes over the BIS index.

  keyword  — SQLite FTS5 / BM25. Exact terms win: IS numbers, gazette S.O.
             numbers, product names, form names. Cannot match paraphrase.
  semantic — dense cosine over BGE-M3 vectors. Matches meaning and works
             across languages, so a Hindi question reaches English text.
             Can drift on rare identifiers a vector has never really seen.
  hybrid   — Reciprocal Rank Fusion of both, plus an identifier boost.
             The default, because the two failure modes above are
             complementary: BM25 anchors the exact citation, dense retrieval
             supplies the paraphrased context around it.

RRF is used rather than score-mixing because BM25 scores and cosine
similarities are on incomparable scales; fusing *ranks* needs no tuning
constant per corpus.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from rag import config, store
from rag.extract import extract_identifiers


class Mode(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


@dataclass
class Hit:
    chunk_id: int
    text: str
    relpath: str
    page_number: int
    title: str
    category: str
    source_url: str | None
    score: float
    sources: set[str] = field(default_factory=set)
    keyword_rank: int | None = None
    semantic_rank: int | None = None
    keyword_score: float | None = None
    semantic_score: float | None = None

    @property
    def citation(self) -> str:
        return f"{self.relpath} p.{self.page_number}"


# FTS5 treats these as query syntax; a user question containing them would
# otherwise raise sqlite3.OperationalError instead of searching.
_FTS_SPECIAL = re.compile(r'[":^*(){}\[\]~/\\+,\-]')

# Dropped from keyword queries: near-zero IDF in this corpus, so they add
# noise without adding ranking signal. Hindi question words are included so
# Hindi queries degrade gracefully on the keyword path too.
_QUERY_STOPWORDS = frozenset("""
what which who whom whose when where why how is are was were be been being do
does did the a an and or of for to in on at by with from as that this these
those it its there their can could shall should will would may might must
have has had i me my we our you your please tell explain about under over
need want know give show list any all some more most other such no not
क्या कौन कौनसा कब कहाँ कहां क्यों कैसे है हैं था थे को का की के में पर से और
या यह वह ये वे कि जो एक मुझे मेरा हमें आप बताओ बताइये कृपया करना करने लिए
""".split())


def build_fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Terms are quoted as literals and OR-ed so partial matches still rank, and
    identifiers ("IS 17440") are kept as quoted phrases so they match as
    units. Question words and function words are dropped: they appear in
    nearly every chunk, so they contribute no IDF while crowding the
    candidate list with noise.
    """
    is_nums, gaz = extract_identifiers(text)
    phrases = [f'"{p}"' for p in (is_nums + gaz) if p.strip()]

    cleaned = _FTS_SPECIAL.sub(" ", text)
    terms = [t for t in cleaned.split() if len(t) > 1]
    content = [t for t in terms if t.lower() not in _QUERY_STOPWORDS]
    # If the question was nothing but stopwords, keep them rather than
    # searching for nothing at all.
    kept = content or terms
    quoted = [f'"{t}"' for t in kept[:40]]

    parts = phrases + quoted
    return " OR ".join(parts) if parts else '""'


def keyword_search(conn: sqlite3.Connection, query: str, k: int) -> list[tuple[int, float]]:
    match = build_fts_query(query)
    if match == '""':
        return []
    try:
        rows = conn.execute(
            """SELECT rowid, bm25(chunks_fts, 1.0, 4.0, 4.0, 0.5) AS score
               FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?""",
            (match, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    # bm25() returns a negative number, better matches more negative.
    return [(int(r["rowid"]), -float(r["score"])) for r in rows]


_vector_cache: tuple[np.ndarray, np.ndarray] | None = None


def _vectors() -> tuple[np.ndarray, np.ndarray]:
    """Load the vector matrix once per process. The API would otherwise
    re-open it on every request."""
    global _vector_cache
    if _vector_cache is None:
        matrix, ids = store.load_vectors()
        _vector_cache = (np.asarray(matrix), ids)
    return _vector_cache


def semantic_search(query: str, k: int) -> list[tuple[int, float]]:
    from rag import embed

    matrix, ids = _vectors()
    if len(ids) == 0:
        return []
    qv = embed.embed_query(query)
    # Vectors are L2-normalised at build time, so this dot product is cosine.
    scores = matrix @ qv
    k = min(k, len(ids))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [(int(ids[i]), float(scores[i])) for i in top]


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = config.RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


def _identifier_boost(conn: sqlite3.Connection, query: str, limit: int) -> list[int]:
    """Chunks whose extracted IS/gazette identifiers literally appear in the
    query. A question naming "IS 17440" should surface that standard even if
    neither ranker put it on top."""
    is_nums, gaz = extract_identifiers(query)
    wanted = [w for w in is_nums + gaz if w.strip()]
    if not wanted:
        return []
    out: list[int] = []
    for want in wanted:
        rows = conn.execute(
            """SELECT id FROM chunks
               WHERE is_numbers LIKE ? OR gazette_refs LIKE ?
               ORDER BY page_number LIMIT ?""",
            (f"%{want}%", f"%{want}%", limit),
        ).fetchall()
        out.extend(int(r["id"]) for r in rows)
    seen: set[int] = set()
    return [i for i in out if not (i in seen or seen.add(i))]


def search(
    query: str,
    *,
    mode: Mode | str = Mode.HYBRID,
    top_k: int = config.DEFAULT_TOP_K,
    candidate_k: int = config.CANDIDATE_K,
    conn: sqlite3.Connection | None = None,
) -> list[Hit]:
    mode = Mode(mode)
    own = conn is None
    conn = conn or store.connect()
    try:
        kw: list[tuple[int, float]] = []
        sem: list[tuple[int, float]] = []

        if mode in (Mode.KEYWORD, Mode.HYBRID):
            kw = keyword_search(conn, query, candidate_k)
        if mode in (Mode.SEMANTIC, Mode.HYBRID):
            sem = semantic_search(query, candidate_k)

        kw_rank = {cid: i for i, (cid, _) in enumerate(kw, 1)}
        sem_rank = {cid: i for i, (cid, _) in enumerate(sem, 1)}
        kw_score = dict(kw)
        sem_score = dict(sem)

        if mode is Mode.KEYWORD:
            ordered = [cid for cid, _ in kw]
            final = {cid: kw_score[cid] for cid in ordered}
        elif mode is Mode.SEMANTIC:
            ordered = [cid for cid, _ in sem]
            final = {cid: sem_score[cid] for cid in ordered}
        else:
            fused = reciprocal_rank_fusion(
                [[cid for cid, _ in kw], [cid for cid, _ in sem]]
            )
            for cid in _identifier_boost(conn, query, top_k):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / config.RRF_K
            ordered = sorted(fused, key=lambda c: fused[c], reverse=True)
            final = fused

        ordered = ordered[:top_k]
        rows = store.fetch_chunks(conn, ordered)

        hits: list[Hit] = []
        for cid in ordered:
            row = rows.get(cid)
            if row is None:
                continue
            sources = set()
            if cid in kw_rank:
                sources.add("keyword")
            if cid in sem_rank:
                sources.add("semantic")
            hits.append(
                Hit(
                    chunk_id=cid,
                    text=row.text,
                    relpath=row.relpath,
                    page_number=row.page_number,
                    title=row.title,
                    category=row.category,
                    source_url=row.source_url,
                    score=float(final.get(cid, 0.0)),
                    sources=sources,
                    keyword_rank=kw_rank.get(cid),
                    semantic_rank=sem_rank.get(cid),
                    keyword_score=kw_score.get(cid),
                    semantic_score=sem_score.get(cid),
                )
            )
        return hits
    finally:
        if own:
            conn.close()
