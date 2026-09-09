"""Shared test isolation.

`rag.search` caches the loaded vector matrix in a module-level global so a
running server does not re-read a 24MB file on every request. In tests that
same global persists across test functions — so once anything loads real
vectors (or another test's fake ones), later tests silently see them too,
including tests that specifically assert "no vectors built yet". Resetting it
before every test closes that leak regardless of which test file introduces it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_vector_cache():
    from rag import search

    search._vector_cache = None
    yield
    search._vector_cache = None
