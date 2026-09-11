"""Routing rules for the sector-split pathway finder.

These lock in the distinctions a wrong answer would cost someone months:
an Indian manufacturer sent to FMCS, a foreign one sent to the domestic ISI
route, or an exporter told to certify goods the Order exempts.
"""

import pytest

from rag import pathway
from rag.pathway import IncompleteAnswers, find_pathway, visible_questions


def _stub_search(monkeypatch):
    """Routing is what is under test; retrieval has its own tests."""
    class Hit:
        relpath, page_number, title, text = "doc.pdf", 1, "Doc", "text"
    monkeypatch.setattr(pathway, "search", lambda *a, **k: [Hit()])


@pytest.mark.parametrize("answers,expected", [
    # An Indian factory and a foreign one must not land on the same scheme.
    (dict(sector="industrial", industry="steel", location="india", trade="domestic"), "ISI"),
    (dict(sector="industrial", industry="steel", location="abroad", trade="domestic"), "FMCS"),
    # Electronics leave the ISI/FMCS split entirely, wherever they are made.
    (dict(sector="industrial", industry="electronics", location="india", trade="domestic"), "CRS"),
    (dict(sector="industrial", industry="electronics", location="abroad", trade="import"), "CRS"),
    # Gold is hallmarking, not product certification.
    (dict(sector="industrial", industry="gold", location="india", trade="domestic"), "HALLMARK"),
    (dict(sector="industrial", industry="gold", location="abroad", trade="import"), "HALLMARK"),
    # Importing is the foreign-manufacturer route even for a plain product.
    (dict(sector="industrial", industry="chemicals", location="abroad", trade="import"), "FMCS"),
    # Export is its own answer: the Orders carve it out.
    (dict(sector="industrial", industry="chemicals", location="india", trade="export"), "EXPORT"),
    (dict(sector="industrial", industry="gold", location="india", trade="export"), "EXPORT"),
    # Consumers get consumer answers.
    (dict(sector="consumer", need="required"), "CONSUMER-REQUIRED"),
    (dict(sector="consumer", need="verify"), "CONSUMER-VERIFY"),
    (dict(sector="consumer", need="complaint"), "CONSUMER-COMPLAINT"),
])
def test_routes(monkeypatch, answers, expected):
    _stub_search(monkeypatch)
    assert find_pathway(answers).scheme_code == expected


def test_export_beats_location(monkeypatch):
    """Export is decided by what happens to the goods, not where the factory
    is — an exporter must not be routed to a domestic marking scheme."""
    _stub_search(monkeypatch)
    for loc in ("india", "abroad"):
        p = find_pathway(dict(sector="industrial", industry="textiles",
                              location=loc, trade="export"))
        assert p.scheme_code == "EXPORT"
    assert "importing country" in p.caveat


def test_consumer_is_never_asked_about_a_factory():
    keys = [q.key for q in visible_questions({"sector": "consumer"})]
    assert keys == ["sector", "need"]
    assert "location" not in keys and "industry" not in keys


def test_company_is_asked_the_full_set():
    keys = [q.key for q in visible_questions({"sector": "industrial"})]
    assert keys == ["sector", "industry", "location", "trade"]


def test_unanswered_questions_never_default_to_a_scheme(monkeypatch):
    """A confident scheme derived from nothing the user said is the failure
    this system exists to prevent."""
    _stub_search(monkeypatch)
    with pytest.raises(IncompleteAnswers):
        find_pathway(dict(sector="industrial", industry="gold"))
    with pytest.raises(IncompleteAnswers):
        find_pathway({})


def test_unknown_option_is_rejected(monkeypatch):
    _stub_search(monkeypatch)
    with pytest.raises(IncompleteAnswers):
        find_pathway(dict(sector="industrial", industry="spaceships",
                          location="india", trade="domestic"))


def test_every_industry_routes_somewhere(monkeypatch):
    """An industry offered in the interface must never dead-end."""
    _stub_search(monkeypatch)
    for value, _, _ in pathway.INDUSTRIES:
        p = find_pathway(dict(sector="industrial", industry=value,
                              location="india", trade="domestic"))
        assert p.scheme_code and p.steps
