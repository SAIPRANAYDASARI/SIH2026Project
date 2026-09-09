"""Shared ML-adjacent clients (embeddings, reranking) used at both index
time (`ingestion.pipeline`) and query time (`app.retrieval`), so the two
never risk drifting onto different models or request shapes and producing
vectors that aren't comparable.
"""
