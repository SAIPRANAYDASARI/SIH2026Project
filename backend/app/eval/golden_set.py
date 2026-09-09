"""The Step 12 full-pipeline golden set: JSONL questions annotated with
what a *correct answer engine response* should look like, not just what
retrieval should surface (that's `app.retrieval.baseline_eval`'s job).

Scope note (see docs/EVALUATION.md and docs/DECISIONS.md, Step 12): the
brief describes a 150+-question set. What ships here (`eval/golden_set_full.jsonl`)
is a much smaller, hand-curated set (~25 questions) chosen to cover every
`Intent` value and both audiences, plus a handful of deliberate
out-of-scope/refusal cases — a real 150+-question set needs domain-expert
review of expected answers at a scale this hackathon build's time budget
doesn't cover. The harness itself scales to any size golden set; only the
data volume is reduced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.models.conversation import Audience
from app.retrieval.query_understanding import Intent


@dataclass(frozen=True)
class GoldenQuestion:
    query: str
    audience: Audience
    expected_intent: Intent
    # True if a well-formed answer to this question should contain at
    # least one valid `[N]` citation (false for a question that should be
    # refused, or answered from the rules engine without a document cite).
    expects_citation: bool
    # True if the correct behavior is the forced-refusal path (retrieval
    # finds nothing / question is genuinely out of scope).
    expects_refusal: bool = False


def load_golden_set(path: Path) -> list[GoldenQuestion]:
    questions = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            questions.append(
                GoldenQuestion(
                    query=record["query"],
                    audience=Audience(record.get("audience", "consumer")),
                    expected_intent=Intent(record["expected_intent"]),
                    expects_citation=record.get("expects_citation", True),
                    expects_refusal=record.get("expects_refusal", False),
                )
            )
    return questions
