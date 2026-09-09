"""Guardrails the brief's legal constraint and citation discipline actually
need enforced in code, not just requested in the prompt — a hosted model
(especially a free-tier one) will not reliably follow prompt instructions
under all inputs, so these checks run on the *generated* answer text after
the fact:

1. **No standard-text redistribution.** Detects any run of more than
   `MAX_VERBATIM_WORDS` consecutive words shared verbatim between the
   answer and a retrieved chunk, and replaces that run with a short
   citation-pointing placeholder — this is the one guardrail that actively
   rewrites the answer, because the legal constraint in `docs/DATA_SOURCES.md`
   ("never redistribute full IS standard text") is a hard requirement, not
   a quality nicety.
2. **No hallucinated grounding.** If retrieval found nothing at all for the
   query, the answer engine (`app.answer.engine`) is told to skip the LLM
   call entirely and return a fixed "not found in indexed sources" message
   — `requires_forced_refusal` is what signals that, checked *before*
   generation rather than after, since there's nothing for the model to
   ground an answer in either way.
3. **Uncited claims are flagged, not silently rewritten.** A claim needing
   a citation that got none is a real quality problem, but auto-editing
   prose to insert a guessed citation would be worse than leaving it
   flagged for the caller (and, eventually, the eval harness in Step 12) to
   see.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from app.retrieval.models import RetrievedChunk

MAX_VERBATIM_WORDS = 25
_PLACEHOLDER = "[standard text omitted — see the cited clause for the original wording]"


@dataclass
class GuardrailReport:
    redacted_text: str
    verbatim_redactions: int = 0
    violations: list[str] = field(default_factory=list)


def requires_forced_refusal(chunks: list[RetrievedChunk]) -> bool:
    """True when there is nothing retrieved to ground an answer in — the
    caller should skip the LLM call and use a fixed refusal message rather
    than risk an ungrounded, uncitable answer."""
    return not chunks


FORCED_REFUSAL_TEXT = (
    "I couldn't find anything about this in the indexed BIS sources. This "
    "assistant only answers from crawled, indexed content — try rephrasing, "
    "or if you believe this should be covered, it may not have been crawled "
    "yet. For anything urgent, check bis.gov.in directly or contact BIS."
)

FORCED_REFUSAL_TEXT_HI = (
    "मुझे इंडेक्स की गई BIS स्रोतों में इस बारे में कोई जानकारी नहीं मिली। यह "
    "सहायक केवल क्रॉल किए गए, इंडेक्स किए गए कॉन्टेंट से ही जवाब देता है — कृपया "
    "सवाल को अलग तरीके से पूछें, या हो सकता है कि यह जानकारी अभी तक क्रॉल न की गई "
    "हो। किसी भी तुरंत जरूरी मामले के लिए bis.gov.in पर सीधे जाएं या BIS से संपर्क करें।"
)


def forced_refusal_text(target_language: str) -> str:
    return FORCED_REFUSAL_TEXT_HI if target_language == "hi" else FORCED_REFUSAL_TEXT


def _redact_verbatim_overlaps(
    answer_words: list[str], chunk_words: list[str]
) -> tuple[list[str], int]:
    matcher = difflib.SequenceMatcher(a=answer_words, b=chunk_words, autojunk=False)
    redactions = 0
    result = list(answer_words)
    # Walk matches longest-first isn't necessary here: get_matching_blocks()
    # already returns non-overlapping blocks in order of position in `a`.
    for block in matcher.get_matching_blocks():
        if block.size > MAX_VERBATIM_WORDS:
            for i in range(block.a, block.a + block.size):
                result[i] = "" if i != block.a else _PLACEHOLDER
            redactions += 1
    return result, redactions


def enforce_guardrails(answer_text: str, chunks: list[RetrievedChunk]) -> GuardrailReport:
    words = answer_text.split(" ")
    total_redactions = 0
    violations: list[str] = []

    for chunk in chunks:
        chunk_words = chunk.text_content.split(" ")
        words, redactions = _redact_verbatim_overlaps(words, chunk_words)
        if redactions:
            total_redactions += redactions
            violations.append(
                f"redacted {redactions} verbatim run(s) of >{MAX_VERBATIM_WORDS} words "
                f"matching chunk {chunk.chunk_id} ({chunk.is_number or 'no IS number'})"
            )

    redacted_text = " ".join(w for w in words if w != "")
    return GuardrailReport(
        redacted_text=redacted_text,
        verbatim_redactions=total_redactions,
        violations=violations,
    )
