"""Embedding client: turns chunk text into the dense vectors
`app.models.document.Chunk.embedding` stores. Local-Ollama-only for now
(the on-premise path decision #3 in docs/DECISIONS.md); a hosted embedding
backend can be added the same way `app.core.config.LLM_BACKEND` switches the
generation model, if a hackathon demo ever needs one.
"""
