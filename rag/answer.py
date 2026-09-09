"""Grounded answering.

This corpus is used to tell people what the law actually requires of them, so
the failure mode that matters is not "unhelpful" — it is a confident answer
that is wrong.

The design separates *being helpful* from *claiming evidence*. Every answer
falls into exactly one clearly-labelled kind, and the user is always told
which one they are reading:

  - grounded      — written from retrieved passages, every fact carrying an
                    [S#] citation that was validated against real sources.
  - extractive    — verbatim quotes from the retrieved passages, no model
                    prose. Used offline, or when generation fails.
  - general       — nothing in the corpus matched, so the model answers from
                    its own knowledge. Explicitly marked unverified, forbidden
                    from stating specific figures as fact, and never allowed
                    to carry a citation marker.

That last kind exists because a bare "not found" leaves a real person with a
real compliance problem no better off. What it must never do is *look* like
evidence — hence grounded=False, no citations, and a distinct label in every
interface that renders it.

Guardrails that hold across all kinds:

  1. A prompt that permits only the supplied passages as source material and
     requires an [S#] marker on every factual sentence.
  2. Post-generation validation. Citation markers are checked against the
     passages actually supplied; invented ones are stripped and reported, and
     an answer citing nothing falls back to quoting the sources directly.
  3. Specific figures — IS numbers, gazette numbers, fees, dates, penalties —
     are never invented in any mode.

Language handling is cross-lingual by design: retrieval runs against the
clean English legal text regardless of question language, and the answer is
written in the user's language with the English source quoted verbatim so the
wording can be checked against the original.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rag import budget, config, llm, scope
from rag.quality import DEVANAGARI
from rag.search import Hit, Mode, search

CITATION = re.compile(r"\[S(\d+)\]")

# Relevance floors, measured against this corpus.
#
# These are checked against COSINE similarity, never the fused RRF score. RRF
# sums reciprocal ranks, so its value depends on where results landed in each
# list, not on how well they match — measured here, "What is the capital of
# France?" scored 0.0323 RRF while the genuinely on-topic "On what grounds can
# BIS cancel a licence?" scored 0.0301. Gating on that number let every
# off-topic question through.
#
# Cosine separates them properly. Measured maximums over the top-k:
#   on-topic BIS questions      0.541 – 0.746
#   clearly unrelated questions 0.402 – 0.427   (cricket, France, cooking)
# 0.50 sits in the gap with room on both sides.
MIN_COSINE = 0.50
MIN_KEYWORD_SCORE = 2.0

SYSTEM_PROMPT = """\
You are Manak Sahayak, an assistant for Indian Standards and Bureau of Indian \
Standards (BIS) matters. People rely on your answers to meet legal and \
compliance obligations, so accuracy matters more than helpfulness.

ABSOLUTE RULES:
1. Use ONLY the numbered SOURCES below. They are the entire body of knowledge \
available to you for this question.
2. You have no other knowledge of BIS. If you believe you know something from \
training data, do not state it — it is not verifiable here.
3. Put an [S#] marker at the end of every sentence that states a fact, naming \
the source it came from. A sentence without a marker must not contain a \
factual claim.
4. If the SOURCES do not answer the question, say so plainly and state what is \
missing. A clear "the indexed documents do not cover this" is a correct and \
valuable answer. Never fill a gap by inference.
5. Never invent or guess: IS numbers, gazette numbers, dates, fee amounts, \
validity periods, penalties, product lists, clause numbers, section numbers, \
regulation numbers, or procedural requirements. If a specific detail is not in \
the SOURCES, say that it is not stated there.
6. If sources conflict, or if a document is an amendment that may have been \
superseded, identify the conflict or uncertainty rather than silently choosing \
one source.
7. Quote the operative wording verbatim when the exact text matters, \
particularly for fees, deadlines, penalties, eligibility, licence conditions, \
cancellation, suspension, or other legal consequences.
8. Distinguish carefully between different legal or administrative actions. Do \
not treat cancellation, suspension, stop-marking, deferment, refusal of \
re-certification, withdrawal, or prosecution as interchangeable. If a source \
describes one of these actions, do not claim that it is another action unless \
the source explicitly says so.
9. Distinguish between:
   * a substantive ground or condition,
   * a procedural requirement,
   * an interim or administrative measure,
   * and a consequence or penalty.
Do not describe a procedural step or consequence as an independent ground for \
cancellation unless the SOURCES explicitly establish it as such.
10. Do not generalise a product-specific, licence-specific, scheme-specific, \
or Indian-Standard-specific requirement to all BIS licences. State the \
applicable scope whenever it is provided in the SOURCES.
11. When the user asks whether a proposed answer is correct, evaluate each \
material claim against the SOURCES. Clearly identify claims that are \
supported, partially supported, unsupported, or contradicted by the SOURCES. \
Do not agree merely because the proposed answer sounds plausible.
12. Do not combine separate statements from different SOURCES into a new legal \
conclusion unless the SOURCES themselves support that conclusion. Where \
necessary, present the statements separately and identify their respective \
sources.
13. When answering a question asking for "grounds", "conditions", \
"requirements", or "reasons", provide only the items that the SOURCES actually \
identify as such. Do not infer additional grounds from related procedures or \
consequences.
14. Output ONLY the final answer. Do not show your reasoning, planning, \
chain-of-thought, source-by-source scanning process, or internal analysis. Do \
not write "Let\u2019s check...", "We need to...", "Looking at each source..." \
or similar narration. Go straight to the answer the user should read.
15. LANGUAGE: Reply in {language}. The sources are in English. When replying \
in another language, give your explanation in that language but quote the \
operative English wording verbatim when the exact wording is legally \
important, so the user can verify it against the original document.
16. CONVERSATION: Earlier turns are provided only to resolve what the user is \
referring to — pronouns, "it", "that scheme", or an unstated subject carried \
over from a previous question. They are NOT a source of facts. Never restate a \
claim from an earlier turn as established unless the SOURCES for THIS question \
support it, and never cite an earlier answer as though it were a document.
"""

USER_TEMPLATE = """\
{history}SOURCES
{sources}

QUESTION
{question}

Answer using only the sources above, with an [S#] marker on every factual \
sentence."""

# How many previous exchanges travel with a question. Enough for "what about
# for foreign manufacturers?" to make sense, short enough that stale context
# does not crowd out the sources — which are what the answer must come from.
HISTORY_TURNS = 3
HISTORY_CHARS = 400

# Used when retrieval finds nothing relevant. A blunt "not found" is honest but
# useless — the user still has a real problem to solve. So the assistant
# answers from general knowledge instead, under two hard constraints: it must
# say up front that this is unverified, and it must not state the specific
# figures people would actually act on (fees, dates, IS numbers, penalties) as
# though they were confirmed. That keeps "helpful" and "never fabricates
# authoritative-looking detail" from being in conflict.
GENERAL_KNOWLEDGE_PROMPT = """\
You are Manak Sahayak, an assistant for Indian Standards and Bureau of Indian \
Standards (BIS) matters.

The indexed BIS document corpus on this system has NO passage relevant to the \
user's question. You must therefore answer from your own general knowledge.

RULES:
1. Answer the question directly. Do NOT open with a disclaimer that this is \
unverified or not based on the documents — the interface already labels the \
answer as general guidance, so repeating it in the text only makes a useful \
answer read as untrustworthy.
2. Genuinely answer the question. Be substantive and practical — explain \
the process, concept, or context as helpfully as you can. Do not stall, and do \
not simply tell the user you have no information.
3. Do NOT state specific IS numbers, gazette/S.O. numbers, fee amounts, exact \
dates, validity periods or penalty figures as established fact. If such a \
detail is genuinely useful, describe it qualitatively ("a fee applies", "there \
is a defined validity period") and tell the user to confirm the exact figure. \
Inventing a plausible-looking number is the single worst thing you can do here.
4. Never write an [S#] citation marker. There are no sources backing this \
answer, so a citation would be a lie.
5. Close with one line on how to get a verified answer: naming a specific \
standard, product or scheme so the indexed documents can be searched, or \
checking bis.gov.in / a BIS branch office.
6. SCOPE: Only answer if the question concerns Indian Standards, BIS \
certification, licensing, hallmarking, Quality Control Orders, testing, \
product compliance or consumer product safety. If it is about anything else \
— a person, sport, films, general trivia, or an unrelated government service \
— do NOT answer it. Say only that the question is outside what you handle and \
that you answer BIS and Indian Standards questions. Never supply the \
off-topic information anyway.

LANGUAGE: Reply in {language}.
"""

GENERAL_KNOWLEDGE_USER = """\
QUESTION
{question}

The indexed BIS documents contain nothing relevant to this. Answer from \
general knowledge, following your rules. Go straight into the answer — no \
disclaimer sentence, \
then actually help."""


@dataclass
class Answer:
    text: str
    hits: list[Hit]
    cited: list[int]
    grounded: bool
    refused: bool
    reason: str = ""
    model: str = ""
    invalid_citations: list[int] = field(default_factory=list)
    mode: str = "hybrid"
    # True when the body is verbatim source extracts rather than a written
    # answer — either offline mode was requested, or generation failed and
    # this is the fallback. Callers must not present it as an AI answer.
    extractive: bool = False
    # True when nothing in the corpus matched and the answer comes from the
    # model's general knowledge. Useful, but unverified — callers MUST label
    # it differently from a cited answer.
    general_knowledge: bool = False

    @property
    def sources(self) -> list[Hit]:
        """Only the passages the answer actually cited."""
        return [self.hits[i - 1] for i in self.cited if 1 <= i <= len(self.hits)]


# What the model is told to write in, keyed by the UI's language code.
LANGUAGE_NAMES = {
    "hi": "Hindi (हिन्दी)",
    "en": "English",
}


def detect_language(text: str) -> str:
    """Devanagari present means answer in Hindi. Deliberately conservative:
    only a script signal, never a guess from content."""
    return "Hindi (हिन्दी)" if DEVANAGARI.search(text) else "English"


def resolve_language(question: str, preferred: str | None) -> str:
    """Which language to answer in.

    Devanagari in the question settles it: someone who typed
    "तुम कौन है?" wants a Hindi answer, whatever the interface is set to.
    That signal is unambiguous, so it outranks the interface preference.

    Otherwise the interface language decides. That matters because English
    text is not a reliable signal of what the reader wants — product and
    legal terms are far easier to type in English, so a Hindi-speaking user
    on a Hindi interface routinely types the question in English and still
    expects the answer in Hindi.

    The two rules together cover all four combinations:
      Hindi question,  any interface   -> Hindi
      English question, Hindi interface -> Hindi
      English question, English/no pref -> English
    """
    if DEVANAGARI.search(question or ""):
        return LANGUAGE_NAMES["hi"]

    if preferred:
        name = LANGUAGE_NAMES.get(preferred.strip().lower())
        if name:
            return name
    return detect_language(question)


def _passes_gate(hits: list[Hit], mode: Mode) -> tuple[bool, str]:
    """Is any retrieved passage actually about this question?"""
    if not hits:
        return False, "no matching passage was found in the indexed corpus"

    # Prefer cosine wherever it exists — it is the only score here that
    # measures similarity rather than rank position.
    cosines = [h.semantic_score for h in hits if h.semantic_score is not None]
    if cosines:
        best = max(cosines)
        if best < MIN_COSINE:
            return False, (
                f"the closest passage matched at {best:.3f} similarity, below the "
                f"{MIN_COSINE} relevance floor — nothing in the corpus is on this topic"
            )
        return True, ""

    # Keyword-only mode has no vectors, so fall back to BM25.
    best = hits[0].score
    if best < MIN_KEYWORD_SCORE:
        return False, (
            f"the closest passage scored {best:.2f} on keyword match, below the "
            f"{MIN_KEYWORD_SCORE} floor — nothing in the corpus is on this topic"
        )
    return True, ""


def format_sources(hits: list[Hit], *, char_limit: int = 1400) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        origin = f"file: {h.relpath}, page {h.page_number}"
        if h.source_url:
            origin += f", downloaded from {h.source_url}"
        blocks.append(f"[S{i}] {h.title}\n({origin})\n{h.text[:char_limit].strip()}")
    return "\n\n".join(blocks)


def _validate(text: str, n_sources: int) -> tuple[str, list[int], list[int]]:
    """Strip citation markers that point at sources that were never supplied."""
    cited, invalid = [], []
    for raw in CITATION.findall(text):
        num = int(raw)
        if 1 <= num <= n_sources:
            if num not in cited:
                cited.append(num)
        elif num not in invalid:
            invalid.append(num)
    for bad in invalid:
        text = text.replace(f"[S{bad}]", "")
    return re.sub(r"[ \t]{2,}", " ", text).strip(), sorted(cited), sorted(invalid)


def _offline_answer(
    question: str, hits: list[Hit], mode: Mode, language: str | None = None
) -> Answer:
    """Extractive answer with zero network calls.

    No model writes anything here: the most query-relevant sentences are
    quoted verbatim from the retrieved passages. That makes this path both
    free and incapable of fabricating, at the cost of not synthesising across
    sources. It is what runs when the LLM is disabled or its budget is spent.
    """
    terms = {
        t.lower()
        for t in re.split(r"\W+", question)
        if len(t) > 2 and t.lower() not in _OFFLINE_STOPWORDS
    }

    lines: list[str] = []
    cited: list[int] = []
    for i, hit in enumerate(hits[:5], 1):
        sentences = [s.strip() for s in re.split(r"(?<=[.;:])\s+", hit.text) if s.strip()]
        scored = sorted(
            sentences,
            key=lambda s: sum(1 for t in terms if t in s.lower()),
            reverse=True,
        )
        best = [s for s in scored[:2] if any(t in s.lower() for t in terms)]
        if not best:
            continue
        cited.append(i)
        lines.append(f"[S{i}] {hit.relpath}, page {hit.page_number}:\n    " + "\n    ".join(best))

    hindi = (language or "").startswith("Hindi")

    if not lines:
        return Answer(
            text=(
                "अनुक्रमित बीआईएस दस्तावेज़ों में इस प्रश्न से पर्याप्त रूप से मेल खाने वाला कोई "
                "अंश नहीं मिला, और कुछ भी अनुमान से नहीं जोड़ा गया है। कृपया किसी विशिष्ट मानक, "
                "उत्पाद या योजना का नाम लेकर पूछें।"
                if hindi else
                "No passage in the indexed BIS documents matches this question "
                "closely enough to quote, and nothing is being inferred. Try "
                "naming a specific standard, product or scheme."
            ),
            hits=hits, cited=[], grounded=False, refused=True,
            reason="no term-matching sentence in retrieved passages", mode=mode.value,
        )

    # Deliberately does not say "offline mode": this path also runs when
    # generation failed, and telling a user they are offline when they are not
    # is its own small lie.
    # The framing is translated, but the quoted passages never are: they are
    # verbatim legal text, and a machine translation presented as the wording
    # of an order would be exactly the kind of unverified claim this system
    # exists to prevent. The Hindi note says so explicitly.
    header = (
        "आधिकारिक बीआईएस दस्तावेज़ों में जो लिखा है, वह हूबहू नीचे दिया गया है। इसका सारांश "
        "या व्याख्या नहीं की गई है, इसलिए इसमें कुछ भी मनगढ़ंत नहीं है — पूरे संदर्भ के लिए "
        "उद्धृत पृष्ठ देखें। (मूल पाठ अंग्रेज़ी में है।)\n"
        if hindi else
        "Here is what the official BIS documents say, quoted exactly. Nothing "
        "below has been summarised or interpreted, so nothing is invented — "
        "open the cited pages for the full context.\n"
    )
    return Answer(
        text=header + "\n" + "\n\n".join(lines),
        hits=hits, cited=cited, grounded=True, refused=False,
        model="offline-extractive (no network call)", mode=mode.value,
        extractive=True,
    )


_OFFLINE_STOPWORDS = frozenset("""
what which who whom when where why how the and for are was were you your can
does did will would shall should must have has had any all some this that
these those under about from with into
""".split())


def format_history(history: list[dict] | None) -> str:
    """Render recent turns as context for interpreting the question.

    Labelled explicitly as context and not evidence. Rule 16 of the system
    prompt tells the model the same thing, and answers are still validated
    against the retrieved sources afterwards, so a claim carried over from an
    earlier turn cannot survive into a cited answer on its own.
    """
    if not history:
        return ""
    recent = [h for h in history if h.get("content")][-HISTORY_TURNS * 2 :]
    if not recent:
        return ""

    lines = []
    for turn in recent:
        who = "User" if turn.get("role") == "user" else "Assistant"
        text = re.sub(r"\s+", " ", str(turn["content"])).strip()[:HISTORY_CHARS]
        if text:
            lines.append(f"{who}: {text}")
    if not lines:
        return ""
    return (
        "CONVERSATION SO FAR (context only — not a source, never cite it)\n"
        + "\n".join(lines)
        + "\n\n"
    )


# Openers that signal the question depends on what came before.
_FOLLOW_UP = re.compile(
    # "What about...", "And for...", "In that case..."
    r"^\s*(?:and\s+)?(?:what|how|why|who|when|where|which)?\s*"
    r"(?:about|for|if|in that case)\b"
    # A bare pronoun subject: "It expires when?", "That scheme..."
    r"|^\s*(?:it|its|that|this|these|those|they|them|the same)\b"
    # A pronoun behind an auxiliary: "Is it...", "Does that...", "Can they..."
    r"|^\s*(?:is|are|was|were|does|do|did|can|could|will|would|should|has|have|had)"
    r"\s+(?:it|its|that|this|these|those|they|them|the same)\b"
    # Trailing modifiers that only make sense against a prior answer.
    r"|\b(?:also|instead|too|as well)\s*\??\s*$",
    re.IGNORECASE,
)


def needs_context(question: str) -> bool:
    """Does this question only make sense against the previous turn?"""
    q = question.strip()
    if len(q.split()) <= 4:
        return True
    return bool(_FOLLOW_UP.search(q))


def expand_query(question: str, history: list[dict] | None) -> str:
    """Give retrieval enough to work with on a follow-up.

    "What about for foreign manufacturers?" carries almost no searchable
    content on its own — embedding it alone retrieves noise. Prefixing the
    previous user question restores the missing subject. Only done when the
    question actually looks dependent, so a self-contained question is never
    polluted by an unrelated earlier topic.
    """
    if not history or not needs_context(question):
        return question
    previous = [h for h in history if h.get("role") == "user" and h.get("content")]
    if not previous:
        return question
    last = re.sub(r"\s+", " ", str(previous[-1]["content"])).strip()[:200]
    return f"{last} {question.strip()}"


def _general_knowledge_answer(
    question: str,
    hits: list[Hit],
    mode: Mode,
    why: str,
    model: str | None = None,
    language: str | None = None,
    history: list[dict] | None = None,
) -> Answer:
    """Answer from the model's own knowledge when the corpus has nothing.

    Returned with grounded=False and general_knowledge=True: it is a real,
    useful answer, but it is not evidence from the indexed documents and must
    never be displayed as though it were.
    """
    language = language or detect_language(question)
    messages = [
        {"role": "system", "content": GENERAL_KNOWLEDGE_PROMPT.format(language=language)},
        {"role": "user", "content": format_history(history)
                                    + GENERAL_KNOWLEDGE_USER.format(question=question.strip())},
    ]

    try:
        response = llm.chat(messages, model=model)
    except llm.LLMError as exc:
        # Nothing retrieved and no model available: there is genuinely nothing
        # to say. Keep it short and practical rather than lecturing the user.
        return Answer(
            text=(
                "अभी इसका उत्तर नहीं दिया जा सका। कृपया कुछ देर बाद दोबारा प्रयास करें, "
                "या किसी विशिष्ट मानक, उत्पाद या योजना का नाम लेकर पूछें।\n\n"
                "आप bis.gov.in पर भी देख सकते हैं।"
                if (language or "").startswith("Hindi") else
                "I could not answer this right now. Please try again in a moment, "
                "or name a specific standard, product or scheme.\n\n"
                "You can also check bis.gov.in directly."
            ),
            hits=hits, cited=[], grounded=False, refused=True,
            reason=f"{why}; general-knowledge fallback also failed: {exc}",
            mode=mode.value,
        )

    # Strip any citation markers the model produced anyway — there are no
    # sources behind this answer, so a marker would imply evidence that does
    # not exist.
    text = CITATION.sub("", response.text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()

    return Answer(
        text=text,
        hits=hits,
        cited=[],
        grounded=False,
        refused=False,
        reason=why,
        model=response.model,
        mode=mode.value,
        general_knowledge=True,
    )


def answer_question(
    question: str,
    *,
    mode: Mode | str = Mode.HYBRID,
    top_k: int = config.DEFAULT_TOP_K,
    model: str | None = None,
    offline: bool = False,
    language: str | None = None,
    history: list[dict] | None = None,
) -> Answer:
    """`language` is the interface language code ("en"/"hi"). When given it
    decides the reply language, so a Hindi interface answers in Hindi even for
    a question typed in English.

    `history` is the recent conversation, used to interpret follow-up
    questions. It never supplies facts — see rule 16 and `format_history`.
    """
    mode = Mode(mode)
    reply_language = resolve_language(question, language)

    # Retrieval runs on the expanded question so a follow-up like "what about
    # for imports?" still searches for the right subject.
    retrieval_query = expand_query(question, history)

    # Small talk is answered directly — instantly, with no retrieval and no
    # model call. "hi" carries no domain vocabulary, so the scope gate below
    # would refuse it, and being told "that is outside what I handle" in reply
    # to a greeting makes the assistant feel broken on first contact.
    intent = scope.classify_intent(question)
    if intent != scope.Intent.QUESTION:
        return Answer(
            text=scope.small_talk_text(intent, reply_language) or "",
            hits=[],
            cited=[],
            grounded=False,
            refused=False,
            reason=f"small talk: {intent}",
            model="direct reply (no model call)",
            mode=mode.value,
        )

    # Refuse off-domain questions before retrieving anything or calling the
    # model. Without this the general-knowledge path answered "who is Virat
    # Kohli" with a full cricket biography under a BIS banner.
    #
    # Judged on the expanded question: a follow-up such as "and for imports?"
    # carries no domain vocabulary of its own and would otherwise be refused
    # in the middle of a legitimate BIS conversation.
    verdict = scope.check_scope(retrieval_query)
    if not verdict.in_scope:
        return Answer(
            text=scope.refusal_text(reply_language),
            hits=[],
            cited=[],
            grounded=False,
            refused=True,
            reason=f"out of scope: {verdict.reason}",
            mode=mode.value,
        )

    hits = search(retrieval_query, mode=mode, top_k=top_k)

    ok, why = _passes_gate(hits, mode)
    if not ok:
        # Nothing in the corpus is on this topic. A flat refusal is honest but
        # leaves the user stuck, so answer from general knowledge instead —
        # clearly marked unverified rather than dressed up as evidence.
        if offline or not config.LLM_ENABLED or budget.remaining() <= 0:
            # No model available to write one, so fall back to whatever the
            # weak hits can supply verbatim.
            return _offline_answer(question, hits, mode, reply_language)
        return _general_knowledge_answer(
            question, hits, mode, why, model, language=reply_language, history=history
        )

    # Explicit offline request, or the LLM is switched off / out of budget.
    # Checked before building a prompt so no request is ever prepared.
    if offline or not config.LLM_ENABLED or budget.remaining() <= 0:
        return _offline_answer(question, hits, mode, reply_language)

    language = reply_language
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=language)},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                history=format_history(history),
                sources=format_sources(hits),
                question=question.strip(),
            ),
        },
    ]

    try:
        response = llm.chat(messages, model=model)
    except llm.LLMError as exc:
        # The hosted model is unavailable, out of budget, or (rarely) returned
        # something unsafe to show, such as leaked chain-of-thought. Rather
        # than surface a raw provider error mid-conversation, fall back to the
        # same zero-cost extractive path offline mode uses — the user still
        # gets a real, cited answer instead of a dead end.
        fallback = _offline_answer(question, hits, mode, reply_language)
        fallback.reason = f"llm_error: {exc}"
        note = (
            "एआई द्वारा तैयार सारांश इस बार उपलब्ध नहीं हो सका, इसलिए नीचे मूल अंश दिए गए हैं:"
            if reply_language.startswith("Hindi")
            else "The AI-generated summary was unavailable this time, so here are "
                 "the exact passages instead:"
        )
        fallback.text = f"{note}\n\n" + fallback.text
        return fallback

    text, cited, invalid = _validate(response.text, len(hits))

    if not cited:
        # The model read the passages and cited none of them. That is the
        # strongest available evidence they do not actually answer the
        # question — stronger than the similarity score, which cannot separate
        # "Which QCO applies to toys?" (0.54, relevant) from "How do I apply
        # for a driving licence?" (0.59, irrelevant but shares vocabulary).
        #
        # So answer from general knowledge instead of quoting passages that
        # are probably off-topic. The retrieved documents still travel with
        # the answer, so a user can judge them for themselves.
        general = _general_knowledge_answer(
            question, hits, mode, "retrieved passages did not support an answer",
            model, language=reply_language, history=history,
        )
        general.invalid_citations = invalid
        return general

    return Answer(
        text=text,
        hits=hits,
        cited=cited,
        grounded=True,
        refused=False,
        model=response.model,
        invalid_citations=invalid,
        mode=mode.value,
    )
