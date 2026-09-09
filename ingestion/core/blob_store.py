"""Content-addressed raw-response blob store.

Every fetched response is written here, keyed by the SHA-256 hash of its raw
bytes, *before* any parsing happens — so a parser bug can never lose the
original source, and re-fetching identical content is naturally a no-op
(the write is skipped if the hash already exists), which is the mechanism
behind "ingestion must be idempotent" in the code quality bar.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def hash_content(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _path_for_hash(self, content_hash: str) -> Path:
        # Two levels of sharding (like git objects) so no single directory
        # accumulates tens of thousands of files.
        return self.root / content_hash[:2] / content_hash[2:4] / content_hash

    def exists(self, content_hash: str) -> bool:
        return self._path_for_hash(content_hash).exists()

    def put(self, content: bytes) -> str:
        """Write `content` if not already present; return its hash and, as
        the caller-facing path, a string relative to `self.root` suitable
        for storing in `Document.blob_path`."""
        content_hash = self.hash_content(content)
        path = self._path_for_hash(content_hash)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return content_hash

    def get(self, content_hash: str) -> bytes:
        return self._path_for_hash(content_hash).read_bytes()

    def relative_path(self, content_hash: str) -> str:
        return str(self._path_for_hash(content_hash).relative_to(self.root))
