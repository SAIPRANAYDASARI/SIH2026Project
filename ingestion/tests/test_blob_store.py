"""BlobStore is content-addressed and idempotent: writing the same bytes
twice does not create a second file, and reading back returns exactly what
was written."""

from __future__ import annotations

from pathlib import Path

from ingestion.core.blob_store import BlobStore


def test_put_then_get_roundtrips(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    content = b"hello manak sahayak"

    content_hash = store.put(content)

    assert store.exists(content_hash)
    assert store.get(content_hash) == content


def test_put_is_idempotent(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)
    content = b"same content twice"

    hash_a = store.put(content)
    hash_b = store.put(content)

    assert hash_a == hash_b
    stored_files = list(tmp_path.rglob("*"))
    stored_files = [p for p in stored_files if p.is_file()]
    assert len(stored_files) == 1


def test_different_content_hashes_differently(tmp_path: Path) -> None:
    store = BlobStore(tmp_path)

    hash_a = store.put(b"content A")
    hash_b = store.put(b"content B")

    assert hash_a != hash_b
