"""Retrieval evaluation across the three modes.

Measures the one thing that decides whether an answer can be correct: does the
document that actually contains the answer appear in the top-k?

The golden set records only *which document* should be retrieved, never an
expected answer text. Expected answers would have to be written by hand and
would themselves become an unverified claim about what the law says; the
document a question is answerable from can be checked by opening the file.

    python -m rag.evaluate
    python -m rag.evaluate --k 5 --set rag/golden_set.jsonl
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from rag.search import Mode, search

DEFAULT_SET = Path(__file__).resolve().parent / "golden_set.jsonl"


@dataclass
class Case:
    question: str
    expect_doc: str  # substring that must appear in a retrieved document path
    note: str = ""
    language: str = "en"


def load_cases(path: Path) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        raw = json.loads(line)
        cases.append(
            Case(
                question=raw["question"],
                expect_doc=raw["expect_doc"],
                note=raw.get("note", ""),
                language=raw.get("language", "en"),
            )
        )
    return cases


def rank_of_expected(hits, expect_doc: str) -> int | None:
    needle = expect_doc.lower()
    for i, h in enumerate(hits, 1):
        if needle in h.relpath.lower():
            return i
    return None


def evaluate(cases: list[Case], *, k: int = 8, modes=tuple(Mode)) -> dict:
    results: dict[str, dict] = {}
    for mode in modes:
        rows = []
        for case in cases:
            try:
                hits = search(case.question, mode=mode, top_k=k)
            except FileNotFoundError:
                rows.append((case, None, "vectors missing"))
                continue
            rows.append((case, rank_of_expected(hits, case.expect_doc), ""))

        found = [r for _, r, _ in rows if r is not None]
        results[mode.value] = {
            "hit_at_k": len(found) / len(rows) if rows else 0.0,
            "hit_at_1": sum(1 for r in found if r == 1) / len(rows) if rows else 0.0,
            "mrr": sum(1.0 / r for r in found) / len(rows) if rows else 0.0,
            "rows": rows,
        }
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="path", type=Path, default=DEFAULT_SET)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cases = load_cases(args.path)
    print(f"{len(cases)} cases from {args.path.name}, k={args.k}\n")
    results = evaluate(cases, k=args.k)

    print(f"{'mode':10s} {'hit@k':>7s} {'hit@1':>7s} {'MRR':>7s}")
    print("-" * 35)
    for mode, r in results.items():
        print(f"{mode:10s} {r['hit_at_k']:7.1%} {r['hit_at_1']:7.1%} {r['mrr']:7.3f}")

    if args.verbose:
        for mode, r in results.items():
            print(f"\n--- {mode} ---")
            for case, rank, err in r["rows"]:
                status = err or (f"rank {rank}" if rank else "MISS")
                print(f"  {status:>10s}  [{case.language}] {case.question[:62]}")
                if rank is None and not err:
                    print(f"              expected: {case.expect_doc}")

    # Hybrid is the default mode, so a regression there is the one that matters.
    hybrid = results.get(Mode.HYBRID.value, {})
    misses = [c.question for c, r, e in hybrid.get("rows", []) if r is None and not e]
    if misses:
        print(f"\nhybrid misses ({len(misses)}):")
        for q in misses:
            print(f"  - {q}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
