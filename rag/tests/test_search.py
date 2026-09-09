"""Retrieval mechanics that must hold regardless of corpus contents."""

from __future__ import annotations

import sqlite3

import pytest

from rag import store
from rag.extract import extract_identifiers
from rag.search import Mode, build_fts_query, keyword_search, reciprocal_rank_fusion


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store.init_schema(c)
    rows = [
        (0, "Hallmarking fee payable by a jeweller to the assaying and hallmarking centre "
            "shall be as specified in Schedule IV.", "", ""),
        (1, "Carbon Black shall conform to IS 17440 : 2020 for the grant of licence.",
            "IS 17440 : 2020", ""),
        (2, "The order is notified vide S.O. 1680(E) dated the fifth of April.",
            "", "S.O. 1680(E)"),
        (3, "Compulsory registration applies to electronic goods under the CRS scheme.", "", ""),
    ]
    for cid, text, isnum, gaz in rows:
        c.execute(
            "INSERT INTO documents(sha256,relpath,filename,title,category,subcategory,"
            "size_bytes,page_count,pages_ok,pages_scanned,pages_corrupt) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (f"sha{cid}", f"d{cid}.pdf", f"d{cid}.pdf", f"Doc {cid}", "cat", "", 1, 1, 1, 0, 0),
        )
        c.execute(
            "INSERT INTO chunks(id,doc_sha,relpath,page_number,ordinal,text,is_numbers,"
            "gazette_refs) VALUES(?,?,?,?,?,?,?,?)",
            (cid, f"sha{cid}", f"d{cid}.pdf", 1, 0, text, isnum, gaz),
        )
        c.execute(
            "INSERT INTO chunks_fts(rowid,text,is_numbers,gazette_refs,title) VALUES(?,?,?,?,?)",
            (cid, text, isnum, gaz, f"Doc {cid}"),
        )
    c.commit()
    yield c
    c.close()


@pytest.mark.parametrize(
    "query",
    [
        'IS 17440:2020 "quoted" (parens)',
        "fee -- for* gold^ jewellery",
        "what is NEAR/2 hallmarking",
        "a AND b OR c NOT d",
        "'; DROP TABLE chunks; --",
        "*",
        "^^^",
    ],
)
def test_hostile_queries_never_raise(conn, query):
    # FTS5 MATCH has its own syntax; unescaped user text would otherwise turn
    # a question into a sqlite3.OperationalError.
    keyword_search(conn, query, 5)


def test_stopwords_are_dropped_from_keyword_queries():
    q = build_fts_query("what is the fee for hallmarking")
    assert '"fee"' in q and '"hallmarking"' in q
    assert '"what"' not in q and '"the"' not in q


def test_all_stopword_query_still_searches_something():
    assert build_fts_query("what is the") != '""'


def test_identifiers_survive_as_phrases():
    assert '"IS 17440 : 2020"' in build_fts_query("does IS 17440 : 2020 apply?")


def test_keyword_search_finds_exact_identifier(conn):
    ids = [cid for cid, _ in keyword_search(conn, "IS 17440", 5)]
    assert 1 in ids


def test_keyword_search_finds_gazette_number(conn):
    ids = [cid for cid, _ in keyword_search(conn, "S.O. 1680(E)", 5)]
    assert 2 in ids


def test_keyword_search_ranks_topical_match_first(conn):
    ids = [cid for cid, _ in keyword_search(conn, "hallmarking fee jeweller", 5)]
    assert ids[0] == 0


def test_keyword_scores_are_descending(conn):
    scores = [s for _, s in keyword_search(conn, "hallmarking licence registration", 5)]
    assert scores == sorted(scores, reverse=True)


def test_rrf_is_symmetric_across_rankers():
    # 'a' tops one ranker and trails the other; 'c' is its mirror image, so
    # fusion must score them identically — order of the input lists must not
    # advantage either retriever.
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"]])
    assert fused["a"] == pytest.approx(fused["c"])
    # 'b' is mid-ranked by both and lands within 1% of the polarised pair,
    # which is the behaviour that makes RRF robust to one bad ranker.
    assert fused["b"] == pytest.approx(fused["a"], rel=0.01)


def test_rrf_ranks_consensus_above_single_ranker_top():
    fused = reciprocal_rank_fusion([["x", "top"], ["y", "top"]])
    assert fused["top"] > fused["x"]


def test_rrf_of_nothing_is_empty():
    assert reciprocal_rank_fusion([[], []]) == {}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("as per IS 17440 : 2020", "IS 17440 : 2020"),
        ("conform to IS 1867:2023", "IS 1867:2023"),
        ("see IS/IEC 62368-1", "IS/IEC 62368-1"),
    ],
)
def test_is_number_extraction(text, expected):
    found, _ = extract_identifiers(text)
    assert any(expected.upper().replace(" ", "") == f.replace(" ", "") for f in found), found


def test_gazette_extraction():
    _, gaz = extract_identifiers("notified vide S.O. 3927(E) dated")
    assert gaz == ["S.O. 3927(E)"]


def test_no_false_identifier_from_plain_text():
    found, gaz = extract_identifiers("The fee is 500 rupees per article.")
    assert found == [] and gaz == []


def test_modes_are_the_three_promised():
    assert {m.value for m in Mode} == {"keyword", "semantic", "hybrid"}
