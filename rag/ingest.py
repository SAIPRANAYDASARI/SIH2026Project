"""Corpus ingestion: PDFs on disk -> searchable index.

Runs in two phases so the expensive one is restartable. Phase 1 (extract,
quality-gate, chunk, write SQLite+FTS) takes a couple of minutes. Phase 2
(embed every chunk on CPU) takes far longer, so it commits vectors as it goes
and can be re-run to fill in only what is missing.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np

from rag import config, store
from rag.chunk import chunk_document
from rag.extract import ExtractedDoc, extract_pdf, iter_pdfs


def _source_urls() -> dict[str, str]:
    """Real download provenance, where the corpus recorded it.

    Only the 13 files in _meta/download_log.csv have a verified source URL.
    Every other document gets NULL rather than a guessed bis.gov.in link — a
    fabricated source URL is exactly the kind of plausible-looking wrong
    detail this system must never emit.
    """
    import csv

    log = config.CORPUS_ROOT / "_meta" / "download_log.csv"
    urls: dict[str, str] = {}
    if not log.exists():
        return urls
    with log.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("filename") or "").strip()
            url = (row.get("source_url") or "").strip()
            if name and url:
                urls[name] = url
    return urls


def build_index(*, limit: int | None = None, verbose: bool = True) -> dict:
    urls = _source_urls()
    conn = store.connect(create=True)
    store.reset(conn)

    pdfs = list(iter_pdfs())
    if limit:
        pdfs = pdfs[:limit]

    stats = Counter()
    chunk_id = 0
    started = time.time()

    seen_sha: dict[str, str] = {}

    for i, path in enumerate(pdfs, 1):
        doc = extract_pdf(path)

        # The corpus stores some documents at several paths (one appears six
        # times, as "__dup2__" filenames). Indexing each copy would let a
        # single passage occupy several top-k slots and crowd out genuinely
        # different sources, so content-identical files are indexed once and
        # the extra paths recorded against the document.
        if doc.sha256 in seen_sha:
            conn.execute(
                "UPDATE documents SET duplicate_paths = json_insert("
                "  CASE WHEN json_valid(duplicate_paths) THEN duplicate_paths ELSE '[]' END,"
                "  '$[#]', ?) WHERE sha256 = ?",
                (doc.relpath, doc.sha256),
            )
            stats["duplicate_files_skipped"] += 1
            continue
        seen_sha[doc.sha256] = doc.relpath

        page_status = Counter(p.status for p in doc.pages)
        drop_reasons: Counter = Counter()
        for p in doc.pages:
            drop_reasons.update(p.dropped_reasons)

        conn.execute(
            """INSERT OR REPLACE INTO documents
               (sha256, relpath, filename, title, category, subcategory, size_bytes,
                page_count, pages_ok, pages_scanned, pages_corrupt, source_url, error,
                page_report)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                doc.sha256,
                doc.relpath,
                doc.filename,
                doc.title,
                doc.category,
                doc.subcategory,
                doc.size_bytes,
                doc.page_count,
                page_status.get("ok", 0),
                page_status.get("scanned", 0),
                page_status.get("mostly_corrupt", 0),
                urls.get(doc.filename),
                doc.error,
                __import__("json").dumps(dict(drop_reasons)),
            ),
        )

        stats["documents"] += 1
        stats["pages"] += doc.page_count
        stats["pages_ok"] += page_status.get("ok", 0)
        stats["pages_scanned"] += page_status.get("scanned", 0)
        stats["pages_corrupt"] += page_status.get("mostly_corrupt", 0)
        if doc.error:
            stats["failed_documents"] += 1

        for ch in chunk_document(doc):
            conn.execute(
                """INSERT INTO chunks
                   (id, doc_sha, relpath, page_number, ordinal, text, is_numbers, gazette_refs)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    chunk_id,
                    ch.doc_sha,
                    ch.relpath,
                    ch.page_number,
                    ch.ordinal,
                    ch.text,
                    ch.is_numbers,
                    ch.gazette_refs,
                ),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid, text, is_numbers, gazette_refs, title) "
                "VALUES (?,?,?,?,?)",
                (chunk_id, ch.text, ch.is_numbers, ch.gazette_refs, doc.title),
            )
            chunk_id += 1
            stats["chunks"] += 1

        if verbose and (i % 25 == 0 or i == len(pdfs)):
            print(
                f"  [{i:3d}/{len(pdfs)}] {stats['chunks']:6d} chunks  "
                f"({time.time() - started:.0f}s)",
                flush=True,
            )
        conn.commit()

    store.set_meta(conn, "corpus_root", str(config.CORPUS_ROOT))
    store.set_meta(conn, "built_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    store.set_meta(conn, "stats", dict(stats))
    store.set_meta(conn, "embedding_model", config.EMBEDDING_MODEL)
    conn.commit()
    conn.close()
    return dict(stats)


def build_vectors(*, batch: int = 256, verbose: bool = True) -> int:
    """Embed every chunk that has no vector yet. Safe to re-run."""
    from rag import embed

    conn = store.connect()
    rows = conn.execute(
        "SELECT id, text FROM chunks WHERE vector_row IS NULL ORDER BY id"
    ).fetchall()
    if not rows:
        if verbose:
            print("  all chunks already embedded")
        conn.close()
        return 0

    existing_matrix: np.ndarray | None = None
    existing_ids: np.ndarray | None = None
    if config.VECTORS_PATH.exists():
        existing_matrix, existing_ids = store.load_vectors()
        existing_matrix = np.asarray(existing_matrix)

    if verbose:
        print(f"  embedding {len(rows)} chunks with {config.EMBEDDING_MODEL} on CPU")

    new_vectors: list[np.ndarray] = []
    new_ids: list[int] = []
    started = time.time()

    for start in range(0, len(rows), batch):
        block = rows[start : start + batch]
        vecs = embed.embed_texts([r["text"] for r in block])
        new_vectors.append(vecs)
        new_ids.extend(int(r["id"]) for r in block)
        if verbose:
            done = start + len(block)
            rate = done / max(time.time() - started, 1e-6)
            remain = (len(rows) - done) / max(rate, 1e-6)
            print(
                f"  [{done:6d}/{len(rows)}] {rate:5.1f} chunks/s  eta {remain/60:5.1f} min",
                flush=True,
            )

    matrix = np.vstack(new_vectors).astype(np.float32)
    ids = np.asarray(new_ids, dtype=np.int64)
    if existing_matrix is not None and existing_ids is not None and len(existing_ids):
        matrix = np.vstack([existing_matrix, matrix])
        ids = np.concatenate([existing_ids, ids])

    store.save_vectors(matrix, ids)
    for row_index, chunk_id in enumerate(ids.tolist()):
        conn.execute("UPDATE chunks SET vector_row=? WHERE id=?", (row_index, chunk_id))
    store.set_meta(conn, "vectors_built_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    conn.commit()
    conn.close()
    return len(new_ids)
