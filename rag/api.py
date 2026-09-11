"""HTTP API for the local BIS RAG.

    python -m uvicorn rag.api:app --port 8100

Deliberately standalone: it has no Postgres, Redis, Celery or Ollama
dependency, so it starts on a plain workstation. Every response carries the
retrieved sources and an explicit grounded/refused flag, so a caller can
always show the user what an answer was based on — or that there was no
basis and none was given.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from rag import budget, config, marks, store
from rag.answer import answer_question
from rag.pathway import QUESTIONS, IncompleteAnswers, find_pathway
from rag.search import Hit, Mode, search

from contextlib import asynccontextmanager


def _warm_up() -> None:
    """Load the embedding model and vectors before the first question.

    BGE-M3 takes ~20s to load on CPU. Without this the first person to use
    the app pays that cost on top of their answer — a poor first impression
    when that person is a judge. Failures are ignored: warming is an
    optimisation, never a reason the server fails to start.
    """
    try:
        from rag.search import Mode as _Mode
        from rag.search import search as _search

        _search("BIS licence", mode=_Mode.HYBRID, top_k=1)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app):
    import threading

    threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(
    title="Manak Sahayak — BIS RAG",
    description="Hybrid multilingual retrieval over the local BIS document corpus.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8100"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Mode = Mode.HYBRID
    top_k: int = Field(default=config.DEFAULT_TOP_K, ge=1, le=50)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Mode = Mode.HYBRID
    top_k: int = Field(default=config.DEFAULT_TOP_K, ge=1, le=20)
    # Verbatim extracts only; makes no network call and cannot cost anything.
    offline: bool = False
    # Interface language code ("en"/"hi"). Decides the language the answer is
    # written in, overriding the script of the question — someone reading a
    # Hindi interface wants a Hindi answer even if they typed in English.
    language: str | None = None
    # Recent turns, so follow-up questions resolve. Context only, never a
    # source of facts — see rule 16 in the system prompt.
    history: list[dict] = Field(default_factory=list)


def serialise(hit: Hit) -> dict:
    return {
        "chunk_id": hit.chunk_id,
        "text": hit.text,
        "document": hit.relpath,
        "page": hit.page_number,
        "title": hit.title,
        "category": hit.category,
        "source_url": hit.source_url,
        "citation": hit.citation,
        "score": round(hit.score, 6),
        "matched_by": sorted(hit.sources),
        "keyword_rank": hit.keyword_rank,
        "semantic_rank": hit.semantic_rank,
    }




STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    try:
        conn = store.connect()
    except FileNotFoundError as exc:
        return {"status": "no_index", "detail": str(exc)}
    chunks = conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
    embedded = conn.execute(
        "SELECT COUNT(*) c FROM chunks WHERE vector_row IS NOT NULL"
    ).fetchone()["c"]
    docs = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    conn.close()
    return {
        "status": "ok",
        "documents": docs,
        "chunks": chunks,
        "chunks_embedded": embedded,
        # Semantic and hybrid need vectors; keyword works without them.
        "semantic_available": embedded > 0,
        "modes": [m.value for m in Mode],
        "llm_enabled": config.LLM_ENABLED,
        "llm_calls_remaining_today": budget.remaining(),
        "llm_daily_call_limit": config.LLM_DAILY_CALL_LIMIT,
    }


@app.get("/usage")
def usage() -> dict:
    """Everything that could ever be billed, and what has been used today."""
    try:
        u = budget.read_usage()
        used = {
            "date": u.date,
            "calls": u.calls,
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
        }
    except budget.BudgetExceeded as exc:
        used = {"error": str(exc)}
    return {
        "billable_endpoint": config.LLM_BASE_URL,
        "llm_enabled": config.LLM_ENABLED,
        "daily_call_limit": config.LLM_DAILY_CALL_LIMIT,
        "max_attempts_per_question": config.LLM_MAX_ATTEMPTS_PER_QUESTION,
        "max_tokens_per_call": config.LLM_MAX_TOKENS,
        "calls_remaining_today": budget.remaining(),
        "today": used,
        "free_by_construction": [
            "pdf extraction", "quality gate", "indexing",
            "embeddings (local BGE-M3)", "keyword search",
            "semantic search", "hybrid search", "offline answering",
        ],
    }


# ── Certification pathway ────────────────────────────────────────────────

class PathwayRequest(BaseModel):
    answers: dict = Field(default_factory=dict)
    language: str | None = None


@app.get("/pathway/questions")
def pathway_questions() -> dict:
    return {
        "questions": [
            {
                "key": q.key,
                "prompt": {"en": q.prompt_en, "hi": q.prompt_hi},
                "options": [
                    {"value": v, "label": {"en": le, "hi": lh}} for v, le, lh in q.options
                ],
                # Lets the interface hide a question that cannot apply yet —
                # a consumer is never asked where their factory is.
                "show_when": q.show_when,
            }
            for q in QUESTIONS
        ]
    }


@app.post("/pathway")
def pathway(req: PathwayRequest) -> dict:
    try:
        p = find_pathway(req.answers, language=req.language or "en")
    except IncompleteAnswers as exc:
        # Better a clear "answer the questions" than a confident scheme
        # derived from nothing the user actually told us.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "scheme": p.scheme,
        "scheme_code": p.scheme_code,
        "summary": p.summary,
        "why": p.why,
        "caveat": p.caveat,
        "sector": p.sector,
        "steps": [
            {"title": s.title, "detail": s.detail, "citations": s.citations} for s in p.steps
        ],
    }


# ── Mark / licence decoder ───────────────────────────────────────────────

class MarkRequest(BaseModel):
    value: str = Field(min_length=1, max_length=100)


@app.post("/decode")
def decode_mark(req: MarkRequest) -> dict:
    r = marks.decode(req.value)
    return {
        "input": r.input,
        "kind": r.kind,
        "recognised": r.recognised,
        "label": r.label,
        "explanation": r.explanation,
        "format_note": r.format_note,
        "caution": r.caution,
        "verify_at": None if not r.verify_at else {"name": r.verify_at[0], "url": r.verify_at[1]},
        "search_hint": r.search_hint,
        "warnings": r.warnings,
    }


@app.get("/stats")
def stats() -> dict:
    conn = store.connect()
    meta = store.get_meta(conn, "stats", {}) or {}
    # Per-document page counts are aggregated WITHOUT joining chunks: joining
    # first multiplies each document's page counts by its number of chunks,
    # which inflated "corrupt pages" to several times the corpus page count.
    categories = [
        dict(r)
        for r in conn.execute(
            """SELECT d.category,
                      COUNT(*) AS documents,
                      SUM(d.page_count)    AS pages,
                      SUM(d.pages_scanned) AS pages_scanned,
                      SUM(d.pages_corrupt) AS pages_corrupt,
                      (SELECT COUNT(*) FROM chunks c
                       JOIN documents d2 ON d2.sha256 = c.doc_sha
                       WHERE d2.category = d.category) AS chunks
               FROM documents d
               GROUP BY d.category ORDER BY d.category"""
        ).fetchall()
    ]
    conn.close()
    return {
        "corpus_root": store_meta_safe("corpus_root"),
        "built_at": store_meta_safe("built_at"),
        "embedding_model": store_meta_safe("embedding_model"),
        "totals": meta,
        "categories": categories,
    }


def store_meta_safe(key: str):
    conn = store.connect()
    try:
        return store.get_meta(conn, key)
    finally:
        conn.close()


@app.post("/search")
def do_search(req: SearchRequest) -> dict:
    try:
        hits = search(req.query, mode=req.mode, top_k=req.top_k)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{exc} — '{req.mode.value}' mode needs dense vectors; "
            "'keyword' mode works without them.",
        ) from exc
    return {
        "query": req.query,
        "mode": req.mode.value,
        "count": len(hits),
        "results": [serialise(h) for h in hits],
    }


@app.post("/compare")
def compare(req: SearchRequest) -> dict:
    """Run one query through all three modes at once.

    Exists for the side-by-side view: seeing which passages each retriever
    finds — and which ones only appear because fusion combined them — is the
    clearest way to show what hybrid retrieval is actually doing.
    """
    out: dict[str, dict] = {}
    per_mode_ids: dict[str, list[int]] = {}

    for mode in Mode:
        try:
            hits = search(req.query, mode=mode, top_k=req.top_k)
            out[mode.value] = {
                "available": True,
                "results": [serialise(h) for h in hits],
            }
            per_mode_ids[mode.value] = [h.chunk_id for h in hits]
        except FileNotFoundError as exc:
            out[mode.value] = {"available": False, "detail": str(exc), "results": []}
            per_mode_ids[mode.value] = []

    kw = set(per_mode_ids.get("keyword", []))
    sem = set(per_mode_ids.get("semantic", []))
    hyb = per_mode_ids.get("hybrid", [])
    return {
        "query": req.query,
        "modes": out,
        "overlap": {
            "keyword_only": sorted(kw - sem),
            "semantic_only": sorted(sem - kw),
            "found_by_both": sorted(kw & sem),
            # Passages hybrid surfaced that neither ranker had in its own
            # top-k — the clearest evidence fusion adds something.
            "hybrid_unique": [c for c in hyb if c not in kw and c not in sem],
        },
    }


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    try:
        result = answer_question(
            req.question, mode=req.mode, top_k=req.top_k, offline=req.offline,
            language=req.language, history=req.history,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "question": req.question,
        "mode": result.mode,
        "answer": result.text,
        "grounded": result.grounded,
        "refused": result.refused,
        "reason": result.reason,
        "model": result.model,
        "invalid_citations": result.invalid_citations,
        # True when the body is verbatim extracts, not a written answer.
        "extractive": result.extractive,
        # True when nothing matched and this is unverified general knowledge.
        "general_knowledge": result.general_knowledge,
        "cited": result.cited,
        # When an answer is refused the retrieved passages are still returned,
        # so the user can read the primary documents themselves.
        "sources": [serialise(h) for h in (result.sources or result.hits)],
    }
