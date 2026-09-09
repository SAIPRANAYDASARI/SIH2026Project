"""API contract and dashboard-figure correctness.

The stats endpoint feeds the numbers shown to users, so a wrong figure there
is a credibility problem, not a cosmetic one. These tests pin the aggregation
that a JOIN fan-out silently corrupted once already.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from rag import api, store


class _Shared:
    """Proxy whose close() is a no-op.

    Endpoints legitimately close the connection they open. An in-memory
    database is destroyed by that, so the fixture hands out a proxy and closes
    the real handle itself at teardown.
    """

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Point vector storage at an empty tmp dir so these tests never touch the
    # real rag_index/vectors.npy — and reset the search-module cache, which
    # persists across tests and would otherwise leak one test's vectors (or
    # the real on-disk ones) into the next.
    from rag import config, search

    monkeypatch.setattr(config, "VECTORS_PATH", tmp_path / "vectors.npy")
    monkeypatch.setattr(config, "VECTOR_IDS_PATH", tmp_path / "vector_ids.npy")
    monkeypatch.setattr(search, "_vector_cache", None)

    real = sqlite3.connect(":memory:", check_same_thread=False)
    real.row_factory = sqlite3.Row
    conn = _Shared(real)
    store.init_schema(conn)

    # Two docs in one category: 10 pages each, 3 corrupt and 1 scanned each.
    # One has many chunks, the other few — the asymmetry is what exposes a
    # fan-out: SUM over a chunk join would scale with chunk count.
    for i, (sha, n_chunks) in enumerate([("s1", 12), ("s2", 2)]):
        conn.execute(
            "INSERT INTO documents(sha256,relpath,filename,title,category,subcategory,"
            "size_bytes,page_count,pages_ok,pages_scanned,pages_corrupt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (sha, f"CAT/{sha}.pdf", f"{sha}.pdf", f"Doc {i}", "03_QCO", "", 1, 10, 6, 1, 3),
        )
        for j in range(n_chunks):
            cid = i * 100 + j
            conn.execute(
                "INSERT INTO chunks(id,doc_sha,relpath,page_number,ordinal,text,"
                "is_numbers,gazette_refs) VALUES(?,?,?,?,?,?,'','')",
                (cid, sha, f"CAT/{sha}.pdf", 1, j, f"text {cid}"),
            )
    store.set_meta(conn, "stats", {"documents": 2, "pages": 20, "pages_ok": 12,
                                   "pages_corrupt": 6, "pages_scanned": 2, "chunks": 14})
    conn.commit()

    monkeypatch.setattr(store, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(api.store, "connect", lambda *a, **k: conn)
    yield TestClient(api.app)
    real.close()


def test_health_reports_index_state(client):
    d = client.get("/health").json()
    assert d["status"] == "ok"
    assert d["documents"] == 2 and d["chunks"] == 14
    assert d["semantic_available"] is False  # no vectors built
    assert set(d["modes"]) == {"keyword", "semantic", "hybrid"}


def test_health_exposes_the_cost_surface(client):
    d = client.get("/health").json()
    for key in ("llm_enabled", "llm_calls_remaining_today", "llm_daily_call_limit"):
        assert key in d


def test_category_page_counts_are_not_multiplied_by_chunks(client):
    """Regression: joining chunks before SUM inflated page figures.

    Two documents with 3 corrupt pages each must report 6 — not 6 x the
    number of chunks, which previously produced counts several times larger
    than the whole corpus.
    """
    cat = client.get("/stats").json()["categories"][0]
    assert cat["pages_corrupt"] == 6
    assert cat["pages_scanned"] == 2
    assert cat["pages"] == 20
    assert cat["documents"] == 2
    assert cat["chunks"] == 14


def test_category_totals_never_exceed_corpus_totals(client):
    d = client.get("/stats").json()
    totals = d["totals"]
    for key in ("pages", "pages_corrupt", "pages_scanned"):
        summed = sum(c[key] or 0 for c in d["categories"])
        assert summed <= totals[key], f"{key}: categories {summed} > corpus {totals[key]}"


def test_usage_endpoint_lists_the_single_billable_endpoint(client):
    d = client.get("/usage").json()
    assert d["billable_endpoint"] == "https://integrate.api.nvidia.com/v1"
    assert "calls_remaining_today" in d
    assert "keyword search" in d["free_by_construction"]


def test_search_without_vectors_is_a_clear_503_not_a_crash(client):
    r = client.post("/search", json={"query": "hallmarking", "mode": "semantic"})
    assert r.status_code == 503
    assert "keyword" in r.json()["detail"]


def test_keyword_search_works_without_vectors(client):
    r = client.post("/search", json={"query": "text", "mode": "keyword", "top_k": 3})
    assert r.status_code == 200
    assert r.json()["mode"] == "keyword"


def test_compare_returns_all_three_modes_and_flags_unavailable(client):
    d = client.post("/compare", json={"query": "text", "top_k": 3}).json()
    assert set(d["modes"]) == {"keyword", "semantic", "hybrid"}
    assert d["modes"]["keyword"]["available"] is True
    # Without vectors these are unavailable, and say so rather than erroring.
    assert d["modes"]["semantic"]["available"] is False
    assert "overlap" in d


def test_rejects_empty_and_oversized_queries(client):
    assert client.post("/search", json={"query": ""}).status_code == 422
    assert client.post("/ask", json={"question": "x" * 5000}).status_code == 422


def test_ask_offline_never_reports_a_hosted_model(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call in offline mode")
    monkeypatch.setattr(api.answer_question.__globals__["llm"], "chat", boom)
    d = client.post("/ask", json={"question": "text", "mode": "keyword", "offline": True}).json()
    assert "no network call" in d["model"] or d["refused"]


def test_home_serves_the_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "Manak Sahayak" in r.text
