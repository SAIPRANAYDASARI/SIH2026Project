"""Builds the messages sent to the LLM: a system prompt that encodes the
citation and legal constraints, plus a user turn carrying the retrieved
chunks as numbered, citable context blocks.

The numbered-bracket citation convention (`[1]`, `[2]`, ...) is what
`app.answer.citations` parses back out of the generated answer — the
prompt and the parser must agree on this format, which is why both live in
`app.answer` rather than the prompt text being duplicated anywhere else.
"""

from __future__ import annotations

from app.llm.client import LLMMessage
from app.models.conversation import Audience
from app.retrieval.models import RetrievedChunk

MAX_VERBATIM_WORDS = 25

_SHARED_RULES = f"""\
You are Manak Sahayak, an assistant for Indian Standards (BIS) certification
questions. You answer only from the numbered context blocks provided below
the question — you have no other knowledge of specific standards, schemes,
fees, or licence data.

Rules, no exceptions:
1. Every factual claim about a standard, scheme, fee, timeline, or
   requirement must end with a citation to the context block it came from,
   like [1] or [2][3] for multiple sources. A sentence with no bracket
   citation is read as your own general commentary, not a sourced fact.
2. If the context blocks do not contain the answer, say so plainly — do not
   guess, and do not fill gaps from general knowledge about standards in
   other countries.
3. Never quote more than about {MAX_VERBATIM_WORDS} consecutive words from
   any context block verbatim. Paraphrase and cite instead. Full Indian
   Standard text is copyrighted and must be purchased from BIS directly —
   you may describe scope and requirements, never reproduce the standard's
   full text.
4. You are not a lawyer or a BIS officer. For anything binding — whether a
   product legally requires certification, whether a licence is valid,
   exact fees — say so is what the indexed sources indicate, and recommend
   confirming with BIS or the listed licensee portal for anything
   consequential.
"""

_INDUSTRY_PROMPT = (
    _SHARED_RULES + "\nAudience: an industry / manufacturer user asking about certification "
    "requirements, schemes (ISI/CRS/FMCS/hallmarking), and compliance "
    "process. Assume basic familiarity with standards but not BIS's internal "
    "processes."
)

_CONSUMER_PROMPT = (
    _SHARED_RULES + "\nAudience: a consumer, possibly reporting a suspected fake or unsafe "
    "product, or asking how to verify a mark/licence. Use plain language, "
    "avoid jargon, and if they describe an unsafe or counterfeit product, "
    "acknowledge the safety concern before answering and mention that BIS's "
    "consumer complaint channel exists for reporting it."
)

# Every answer should be a thorough, easy-to-follow explanation rather than
# a terse one-liner: spell out what a term means, why it matters, and what
# the reader should actually do next — while staying within the citation
# and grounding rules above (detail must still trace back to [N] markers,
# not filled in from general knowledge).
_DETAIL_INSTRUCTION = (
    "\nGive a thorough, detailed explanation, not a one-line answer — cover what "
    "the term/process means, why it matters, and any next step the reader should "
    "take, using short sentences and everyday words a non-expert would understand. "
    "Still follow the citation rules above for every factual claim."
)

# Language directive: the whole answer (not just a translated tail) must be
# written natively in the requested language, in plain conversational
# register — machine-translating an English answer after the fact reads
# stiffly and can mangle citation brackets, so the LLM writes it directly.
_LANGUAGE_INSTRUCTIONS: dict[str, str] = {
    "en": "\nWrite your entire answer in simple, plain English.",
    "hi": (
        "\nWrite your entire answer in Hindi (Devanagari script, सरल हिंदी में) — "
        "use everyday spoken Hindi, not heavy Sanskritized/formal Hindi. Keep technical "
        "terms that don't have a common Hindi equivalent (e.g. product or scheme names, "
        "IS numbers) in their original form. Citation markers like [1] must stay exactly "
        "as [1] — never translate or reformat them."
    ),
}


def system_prompt(audience: Audience, target_language: str = "en") -> str:
    base = _INDUSTRY_PROMPT if audience is Audience.INDUSTRY else _CONSUMER_PROMPT
    language_instruction = _LANGUAGE_INSTRUCTIONS.get(target_language, _LANGUAGE_INSTRUCTIONS["en"])
    return base + _DETAIL_INSTRUCTION + language_instruction


def format_context_blocks(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(No matching context was found in the indexed BIS sources for this query.)"

    blocks = []
    for i, chunk in enumerate(chunks, start=1):
        header_parts = [chunk.is_number or "(no IS number)"]
        if chunk.clause_number:
            header_parts.append(f"clause {chunk.clause_number}")
        if chunk.section_path:
            header_parts.append(chunk.section_path)
        header = " — ".join(header_parts)
        title = chunk.document_title or "(untitled source)"
        blocks.append(f"[{i}] {title} ({header})\n{chunk.text_content}")
    return "\n\n".join(blocks)


def build_messages(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    audience: Audience,
    target_language: str = "en",
) -> list[LLMMessage]:
    context = format_context_blocks(chunks)
    user_content = f"Context blocks:\n\n{context}\n\nQuestion: {query}"
    return [
        LLMMessage(role="system", content=system_prompt(audience, target_language)),
        LLMMessage(role="user", content=user_content),
    ]
