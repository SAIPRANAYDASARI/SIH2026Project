"""Command line interface.

    python -m rag.cli build            # extract + chunk + index (fast)
    python -m rag.cli embed            # build dense vectors (slow, resumable)
    python -m rag.cli stats            # corpus and index coverage
    python -m rag.cli search "..."     # inspect retrieval, any mode
    python -m rag.cli ask "..."        # grounded answer with citations
    python -m rag.cli compare "..."    # same query through all three modes
"""

from __future__ import annotations

import argparse
import sys

from rag import config, store
from rag.search import Mode, search


def _print_hit(i: int, h, *, text_chars: int = 240) -> None:
    tags = "+".join(sorted(h.sources)) or "-"
    print(f"\n[{i}] score={h.score:.4f}  via={tags}")
    print(f"    {h.title}")
    print(f"    {h.relpath}  page {h.page_number}")
    detail = []
    if h.keyword_rank:
        detail.append(f"bm25 #{h.keyword_rank} ({h.keyword_score:.2f})")
    if h.semantic_rank:
        detail.append(f"cosine #{h.semantic_rank} ({h.semantic_score:.3f})")
    if detail:
        print("    " + "  ".join(detail))
    body = " ".join(h.text.split())
    print(f"    {body[:text_chars]}{'...' if len(body) > text_chars else ''}")


def cmd_build(args) -> int:
    from rag.ingest import build_index

    print(f"Indexing corpus at {config.CORPUS_ROOT}")
    stats = build_index(limit=args.limit)
    print("\nIndex built:")
    for key, value in stats.items():
        print(f"  {key:18s} {value}")
    print(f"\n  -> {config.DB_PATH}")
    print("\nNext:  python -m rag.cli embed")
    return 0


def cmd_embed(args) -> int:
    from rag.ingest import build_vectors

    n = build_vectors(batch=args.batch)
    print(f"\nEmbedded {n} chunks -> {config.VECTORS_PATH}")
    return 0


def cmd_stats(args) -> int:
    conn = store.connect()
    meta = store.get_meta(conn, "stats", {}) or {}
    print("INDEX")
    print(f"  corpus        {store.get_meta(conn, 'corpus_root')}")
    print(f"  built         {store.get_meta(conn, 'built_at')}")
    print(f"  vectors built {store.get_meta(conn, 'vectors_built_at') or 'NOT BUILT'}")
    print(f"  embed model   {store.get_meta(conn, 'embedding_model')}")

    print("\nCOVERAGE")
    for key in ("documents", "pages", "pages_ok", "pages_scanned", "pages_corrupt", "chunks"):
        if key in meta:
            print(f"  {key:15s} {meta[key]}")
    pages = meta.get("pages") or 0
    if pages:
        print(f"  usable page %   {100 * meta.get('pages_ok', 0) / pages:.1f}%")

    embedded = conn.execute(
        "SELECT COUNT(*) c FROM chunks WHERE vector_row IS NOT NULL"
    ).fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
    print(f"  chunks embedded {embedded}/{total}")

    print("\nBY CATEGORY")
    # Page counts are aggregated over documents only. Joining chunks first
    # would multiply each document's page counts by its chunk count.
    rows = conn.execute(
        """SELECT d.category,
                  COUNT(*) AS docs,
                  SUM(d.pages_scanned) AS scanned,
                  SUM(d.pages_corrupt) AS corrupt,
                  (SELECT COUNT(*) FROM chunks c
                   JOIN documents d2 ON d2.sha256 = c.doc_sha
                   WHERE d2.category = d.category) AS chunks
           FROM documents d
           GROUP BY d.category ORDER BY d.category"""
    ).fetchall()
    print(f"  {'category':28s} {'docs':>5s} {'chunks':>7s} {'scan':>5s} {'corrupt':>8s}")
    for r in rows:
        print(
            f"  {r['category'][:28]:28s} {r['docs']:5d} {r['chunks']:7d} "
            f"{r['scanned'] or 0:5d} {r['corrupt'] or 0:8d}"
        )

    failed = conn.execute(
        "SELECT relpath, error FROM documents WHERE error IS NOT NULL"
    ).fetchall()
    if failed:
        print(f"\nUNREADABLE DOCUMENTS ({len(failed)})")
        for r in failed:
            print(f"  {r['relpath']}: {r['error']}")

    noscan = conn.execute(
        "SELECT relpath, page_count, pages_scanned FROM documents "
        "WHERE pages_scanned > 0 ORDER BY pages_scanned DESC LIMIT 10"
    ).fetchall()
    if noscan:
        print("\nTOP SCANNED (no text layer — would need OCR to index)")
        for r in noscan:
            print(f"  {r['pages_scanned']:4d}/{r['page_count']:<4d}  {r['relpath']}")
    conn.close()
    return 0


def cmd_search(args) -> int:
    hits = search(args.query, mode=args.mode, top_k=args.k)
    print(f"mode={args.mode}  query={args.query!r}  hits={len(hits)}")
    if not hits:
        print("\nNo matches.")
    for i, h in enumerate(hits, 1):
        _print_hit(i, h)
    return 0


def cmd_compare(args) -> int:
    for mode in (Mode.KEYWORD, Mode.SEMANTIC, Mode.HYBRID):
        print("\n" + "=" * 78)
        print(f"MODE: {mode.value}")
        print("=" * 78)
        try:
            hits = search(args.query, mode=mode, top_k=args.k)
        except FileNotFoundError as exc:
            print(f"  unavailable: {exc}")
            continue
        for i, h in enumerate(hits, 1):
            print(f"  [{i}] {h.score:8.4f}  {h.relpath} p.{h.page_number}")
            print(f"       {' '.join(h.text.split())[:110]}")
    return 0


def cmd_ask(args) -> int:
    from rag.answer import answer_question

    result = answer_question(args.query, mode=args.mode, top_k=args.k, offline=args.offline)

    print("=" * 78)
    print(result.text)
    print("=" * 78)

    if result.refused:
        print(f"\nSTATUS: refused ({result.reason})")
    else:
        print(f"\nSTATUS: grounded  model={result.model}  mode={result.mode}")
    if result.invalid_citations:
        print(f"WARNING: model cited non-existent sources {result.invalid_citations} (removed)")

    shown = result.sources if result.cited else result.hits
    label = "CITED SOURCES" if result.cited else "RETRIEVED PASSAGES (read directly)"
    print(f"\n{label}")
    for i, h in enumerate(shown, 1):
        num = result.cited[i - 1] if result.cited else i
        print(f"\n [S{num}] {h.title}")
        print(f"       {h.relpath}  page {h.page_number}")
        if h.source_url:
            print(f"       source: {h.source_url}")
        if args.verbose:
            print(f"       {' '.join(h.text.split())[:400]}")
    return 0


def cmd_usage(args) -> int:
    from rag import budget

    print("LLM COST SURFACE")
    print(f"  enabled            {config.LLM_ENABLED}")
    print(f"  endpoint           {config.LLM_BASE_URL}")
    print(f"  daily call limit   {config.LLM_DAILY_CALL_LIMIT}")
    print(f"  max attempts/query {config.LLM_MAX_ATTEMPTS_PER_QUESTION}")
    print(f"  max tokens/call    {config.LLM_MAX_TOKENS}")
    try:
        u = budget.read_usage()
        print(f"\nTODAY ({u.date})")
        print(f"  calls made         {u.calls} / {config.LLM_DAILY_CALL_LIMIT}")
        print(f"  prompt tokens      {u.prompt_tokens}")
        print(f"  completion tokens  {u.completion_tokens}")
        print(f"  total tokens       {u.total_tokens}")
        print(f"  calls remaining    {budget.remaining()}")
    except budget.BudgetExceeded as exc:
        print(f"\n  {exc}")
    print("\nEverything else — extraction, indexing, embeddings, and all three")
    print("search modes — runs locally and makes no network call.")
    print("Use  --offline  on 'ask', or set BIS_LLM_ENABLED=false, for zero calls.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rag.cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="extract, quality-gate, chunk and index the corpus")
    p.add_argument("--limit", type=int, default=None, help="only the first N PDFs")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("embed", help="build dense vectors (resumable)")
    p.add_argument("--batch", type=int, default=256)
    p.set_defaults(func=cmd_embed)

    p = sub.add_parser("stats", help="corpus and index coverage")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("search", help="inspect retrieval")
    p.add_argument("query")
    p.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.HYBRID.value)
    p.add_argument("-k", type=int, default=config.DEFAULT_TOP_K)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("compare", help="run one query through all three modes")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("ask", help="grounded answer with citations")
    p.add_argument("query")
    p.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.HYBRID.value)
    p.add_argument("-k", type=int, default=config.DEFAULT_TOP_K)
    p.add_argument("-v", "--verbose", action="store_true", help="print source text")
    p.add_argument(
        "--offline", action="store_true",
        help="answer with verbatim extracts only — makes no network call and cannot cost anything",
    )
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("usage", help="hosted-LLM calls and tokens used today")
    p.set_defaults(func=cmd_usage)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
