"""Retrieval core: hybrid BM25 + dense search, reciprocal rank fusion,
cross-encoder reranking, and the query-understanding layer that detects
exact identifiers and classifies intent ahead of retrieval.

This is a service module — no FastAPI routes live here (Step 6 wires
`app.api.v1.chat`/`standards`/etc. to call into `hybrid_search`), and no
business logic belongs in route handlers instead of here, per the
architecture's "routes call service classes" rule.

`cli.py` gives a way to interrogate this layer directly, before the answer
engine (Step 5) or the API surface (Step 6) exist — `python -m
app.retrieval.cli query "<question>"` from inside the backend container.
"""
