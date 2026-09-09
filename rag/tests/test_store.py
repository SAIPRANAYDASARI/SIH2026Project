"""Index storage and provenance."""

from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest

from rag import store


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store.init_schema(c)
    yield c
    c.close()


def insert_doc(c, sha="s1", relpath="a/b.pdf", title="Doc", url=None):
    c.execute(
        "INSERT INTO documents(sha256,relpath,filename,title,category,subcategory,"
        "size_bytes,page_count,pages_ok,pages_scanned,pages_corrupt,source_url) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (sha, relpath, "b.pdf", title, "cat", "", 10, 3, 3, 0, 0, url),
    )


def insert_chunk(c, cid=1, sha="s1", relpath="a/b.pdf", page=2, text="text"):
    c.execute(
        "INSERT INTO chunks(id,doc_sha,relpath,page_number,ordinal,text,is_numbers,"
        "gazette_refs) VALUES(?,?,?,?,?,?,'','')",
        (cid, sha, relpath, page, 0, text),
    )


def test_fetch_chunks_carries_citation_fields(conn):
    insert_doc(conn)
    insert_chunk(conn, text="A provision.")
    row = store.fetch_chunks(conn, [1])[1]
    # These four are what a citation is built from; losing any makes an
    # answer uncheckable.
    assert row.relpath == "a/b.pdf"
    assert row.page_number == 2
    assert row.title == "Doc"
    assert row.text == "A provision."


def test_fetch_chunks_of_nothing_is_empty(conn):
    assert store.fetch_chunks(conn, []) == {}


def test_fetch_chunks_ignores_unknown_ids(conn):
    insert_doc(conn)
    insert_chunk(conn)
    assert set(store.fetch_chunks(conn, [1, 999])) == {1}


def test_source_url_is_null_when_unknown(conn):
    # A guessed bis.gov.in URL would look like verified provenance, so
    # documents with no recorded download keep NULL.
    insert_doc(conn)
    insert_chunk(conn)
    assert store.fetch_chunks(conn, [1])[1].source_url is None


def test_source_url_is_preserved_when_known(conn):
    insert_doc(conn, url="https://www.bis.gov.in/x.pdf")
    insert_chunk(conn)
    assert store.fetch_chunks(conn, [1])[1].source_url == "https://www.bis.gov.in/x.pdf"


def test_duplicate_paths_default_to_empty_list(conn):
    insert_doc(conn)
    row = conn.execute("SELECT duplicate_paths FROM documents").fetchone()
    assert json.loads(row["duplicate_paths"]) == []


def test_duplicate_paths_accumulate(conn):
    insert_doc(conn)
    for path in ("x/dup1.pdf", "y/dup2.pdf"):
        conn.execute(
            "UPDATE documents SET duplicate_paths = json_insert(duplicate_paths,'$[#]',?) "
            "WHERE sha256='s1'",
            (path,),
        )
    row = conn.execute("SELECT duplicate_paths FROM documents").fetchone()
    assert json.loads(row["duplicate_paths"]) == ["x/dup1.pdf", "y/dup2.pdf"]


def test_meta_roundtrips_structured_values(conn):
    store.set_meta(conn, "stats", {"documents": 240, "chunks": 5937})
    assert store.get_meta(conn, "stats")["chunks"] == 5937


def test_meta_upserts_rather_than_duplicating(conn):
    store.set_meta(conn, "k", 1)
    store.set_meta(conn, "k", 2)
    assert store.get_meta(conn, "k") == 2
    assert conn.execute("SELECT COUNT(*) c FROM meta").fetchone()["c"] == 1


def test_missing_meta_returns_default(conn):
    assert store.get_meta(conn, "absent", "fallback") == "fallback"


def test_reset_clears_content_but_keeps_schema(conn):
    insert_doc(conn)
    insert_chunk(conn)
    store.reset(conn)
    assert conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"] == 0


def test_vectors_roundtrip(tmp_path, monkeypatch):
    from rag import config

    monkeypatch.setattr(config, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(config, "VECTORS_PATH", tmp_path / "v.npy")
    monkeypatch.setattr(config, "VECTOR_IDS_PATH", tmp_path / "i.npy")

    matrix = np.random.rand(5, 8).astype(np.float32)
    ids = np.arange(5, dtype=np.int64)
    store.save_vectors(matrix, ids)
    loaded, loaded_ids = store.load_vectors()
    assert np.allclose(np.asarray(loaded), matrix)
    assert list(loaded_ids) == list(ids)


def test_missing_vectors_raise_actionable_error(tmp_path, monkeypatch):
    from rag import config

    monkeypatch.setattr(config, "VECTORS_PATH", tmp_path / "nope.npy")
    with pytest.raises(FileNotFoundError, match="rag.cli build"):
        store.load_vectors()


def test_connect_to_missing_index_explains_how_to_build(tmp_path):
    with pytest.raises(FileNotFoundError, match="rag.cli build"):
        store.connect(tmp_path / "absent.sqlite3")
