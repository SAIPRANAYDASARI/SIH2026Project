"""Grounding guarantees.

These are the tests that matter most for a system people use to work out
their legal obligations: the assistant must refuse rather than improvise, and
must never present a claim that cannot be traced to a supplied passage.
"""

from __future__ import annotations

import pytest

from rag import answer as answer_mod
from rag.answer import Answer, _validate, answer_question, detect_language, format_sources
from rag.search import Hit, Mode


def make_hit(
    chunk_id=1,
    score=0.05,
    text="Some legal text about hallmarking fees.",
    cosine=0.70,
):
    """A retrieved passage. `cosine` defaults to a comfortably relevant value
    because that is what the relevance gate actually judges — tests that want
    an off-topic hit pass a low one explicitly."""
    return Hit(
        chunk_id=chunk_id,
        text=text,
        relpath="07_HALLMARKING/REGULATIONS/x.pdf",
        page_number=12,
        title="Hallmarking Regulations",
        category="07_HALLMARKING",
        source_url=None,
        score=score,
        semantic_score=cosine,
    )


@pytest.fixture
def no_llm(monkeypatch):
    """Fail loudly if the LLM is called when it should not be."""
    def boom(*a, **k):
        raise AssertionError("LLM must not be called")
    monkeypatch.setattr(answer_mod.llm, "chat", boom)


@pytest.fixture
def general_llm(monkeypatch):
    """Stand-in for the model answering from its own knowledge."""
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse(
            "This is general information, not verified against the indexed "
            "documents. BIS certification generally involves applying, testing "
            "and an audit. Confirm exact fees with BIS.",
            "test-model",
        ),
    )


# ── When the corpus has nothing ──────────────────────────────────────────
#
# A bare "not found" is honest but leaves a real compliance question
# unanswered, so the assistant answers from general knowledge instead. The
# safety requirement is not silence — it is that such an answer can never be
# mistaken for evidence from the documents.


def test_nothing_retrieved_still_answers_from_general_knowledge(monkeypatch, general_llm):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    result = answer_question("how does BIS certification work in general")
    assert result.general_knowledge is True
    assert result.refused is False          # the user is not left stuck
    assert result.grounded is False         # but this is not evidence
    assert result.cited == []


def test_below_floor_match_still_answers_from_general_knowledge(monkeypatch, general_llm):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit(cosine=0.41)])
    # In-domain question, but nothing in the corpus is close enough to it.
    result = answer_question("How does BIS certification compare with CE marking?")
    assert result.general_knowledge and not result.grounded
    assert "relevance floor" in result.reason


def test_general_knowledge_answer_never_carries_a_citation(monkeypatch):
    """A citation marker would imply document evidence that does not exist."""
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse("Licences may be cancelled. [S1]", "m"),
    )
    result = answer_question("anything")
    assert "[S1]" not in result.text
    assert result.cited == []


def test_gate_uses_cosine_not_the_fused_rank_score():
    """Regression: the gate previously compared the RRF score, which measures
    rank position rather than similarity. Measured on this corpus, "capital of
    France" scored 0.0323 RRF against 0.0301 for a real BIS question — so
    every off-topic question passed. Cosine separates them."""
    from rag.answer import _passes_gate
    from rag.search import Mode

    off_topic = make_hit(score=0.0323)      # high fused score...
    off_topic.semantic_score = 0.42         # ...but plainly unrelated
    ok, why = _passes_gate([off_topic], Mode.HYBRID)
    assert ok is False and "similarity" in why

    on_topic = make_hit(score=0.0301)       # lower fused score...
    on_topic.semantic_score = 0.74          # ...but genuinely relevant
    assert _passes_gate([on_topic], Mode.HYBRID)[0] is True


def test_keyword_only_mode_falls_back_to_bm25_gate():
    """Keyword mode has no vectors, so cosine is unavailable by design."""
    from rag.answer import _passes_gate
    from rag.search import Mode

    weak = make_hit(score=0.5)
    weak.semantic_score = None
    assert _passes_gate([weak], Mode.KEYWORD)[0] is False

    strong = make_hit(score=15.0)
    strong.semantic_score = None
    assert _passes_gate([strong], Mode.KEYWORD)[0] is True


def test_empty_results_never_pass_the_gate():
    from rag.answer import _passes_gate
    from rag.search import Mode

    assert _passes_gate([], Mode.HYBRID)[0] is False


def test_general_knowledge_prompt_forbids_inventing_figures():
    prompt = answer_mod.GENERAL_KNOWLEDGE_PROMPT.lower()
    assert "do not state specific" in prompt
    # Must forbid the categories people actually act on.
    for risky in ("fee", "date", "penalty", "gazette"):
        assert risky in prompt


def test_general_knowledge_answer_carries_no_citation_markers():
    """A citation would imply document backing that does not exist. The
    provenance is carried by the interface label, not by faking a source."""
    assert "never write an [s#]" in answer_mod.GENERAL_KNOWLEDGE_PROMPT.lower()


def test_general_knowledge_prompt_does_not_ask_for_a_disclaimer_sentence():
    """The interface labels these answers as general guidance. Having the
    model also open with "this is not verified" said it twice and made a
    genuinely useful answer read as untrustworthy."""
    prompt = answer_mod.GENERAL_KNOWLEDGE_PROMPT.lower()
    assert "do not open with a disclaimer" in prompt


def test_general_knowledge_falls_back_gracefully_when_llm_is_down(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    def fail(*a, **k):
        raise answer_mod.llm.LLMError("503 overloaded")
    monkeypatch.setattr(answer_mod.llm, "chat", fail)
    result = answer_question("anything")
    assert result.refused and not result.general_knowledge


def test_offline_mode_does_not_reach_for_general_knowledge(monkeypatch, no_llm):
    """Offline promises no network call — that holds even with no matches."""
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    result = answer_question("anything", offline=True)
    assert not result.general_knowledge


def test_uncited_claim_is_never_shown_as_sourced_fact(monkeypatch):
    """The model stated a figure but cited nothing. That claim must not be
    presented as though the documents backed it."""
    calls = []

    def chat(messages, **k):
        calls.append(messages)
        # First call: uncited claim. Second: the general-knowledge retry.
        if len(calls) == 1:
            return answer_mod.llm.LLMResponse("The fee is 200 rupees.", "m")
        return answer_mod.llm.LLMResponse("Fees vary; confirm with BIS.", "m")

    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(answer_mod.llm, "chat", chat)

    result = answer_question("what is the hallmarking fee")
    assert "200 rupees" not in result.text
    assert result.grounded is False
    assert result.general_knowledge is True
    assert result.reason == "retrieved passages did not support an answer"
    # The documents still travel with the answer so the user can judge them.
    assert result.hits


def test_invented_citation_is_stripped_and_reported(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse(
            "Hallmarking is required. [S1] The fee doubled in 2019. [S7]", "m"
        ),
    )
    result = answer_question("hallmarking rules")
    assert result.grounded
    assert result.cited == [1]
    assert result.invalid_citations == [7]
    assert "[S7]" not in result.text


def test_llm_failure_degrades_to_offline_extraction_not_a_raw_error(monkeypatch):
    """A live demo must never dead-end on a provider error: total LLM failure
    (down, out of budget, or unsafe output rejected) still returns a real,
    cited answer via the same verbatim-extraction path offline mode uses."""
    source = "The hallmarking fee shall be as specified in Schedule IV."
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit(text=source)])
    def fail(*a, **k):
        raise answer_mod.llm.LLMError("HTTP 500 from nvidia/x: internal-server-error")
    monkeypatch.setattr(answer_mod.llm, "chat", fail)

    result = answer_question("what is the hallmarking fee")
    assert result.grounded and not result.refused
    assert source in result.text          # still gives the real source text
    # The provider's raw error is diagnostic detail, not something to show a
    # user mid-conversation — it stays in `reason`.
    assert "500" in result.reason and "llm_error" in result.reason
    assert "internal-server-error" not in result.text
    assert "unavailable" in result.text   # user gets a plain explanation


def test_llm_failure_note_does_not_replace_the_extraction(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: (_ for _ in ()).throw(answer_mod.llm.LLMError("503 overloaded")),
    )
    result = answer_question("hallmarking rules")
    assert result.cited  # extraction still found and cited a passage


def test_grounded_answer_exposes_only_cited_sources(monkeypatch):
    hits = [make_hit(1), make_hit(2), make_hit(3)]
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: hits)
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse("Fact one. [S1] Fact three. [S3]", "m"),
    )
    result = answer_question("hallmarking rules")
    assert result.cited == [1, 3]
    assert [h.chunk_id for h in result.sources] == [1, 3]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("What is the hallmarking fee?", "English"),
        ("हॉलमार्किंग शुल्क क्या है?", "Hindi (हिन्दी)"),
        ("BIS licence की वैधता", "Hindi (हिन्दी)"),
    ],
)
def test_language_detection(text, expected):
    assert detect_language(text) == expected


# ── Interface language wins over question script ─────────────────────────
#
# Users reading the Hindi interface often type the question in English,
# because product and legal terms are easier that way. Answering in English
# because of that left most of the page untranslated.


def test_devanagari_question_answers_in_hindi_whatever_the_interface():
    """Reported from the running app: a Hindi question on an English
    interface was answered in English. Devanagari is an unambiguous signal
    of what the reader wants, so it outranks the interface setting."""
    from rag.answer import resolve_language

    assert resolve_language("हॉलमार्किंग शुल्क क्या है?", "en") == "Hindi (हिन्दी)"
    assert resolve_language("तुम कौन है?", "en") == "Hindi (हिन्दी)"


def test_interface_language_decides_for_english_text():
    """English text is NOT a reliable signal: product and legal terms are
    easier to type in English, so a Hindi reader often types in English and
    still wants a Hindi answer. The interface setting decides there."""
    from rag.answer import resolve_language

    assert resolve_language("What is the hallmarking fee?", "hi") == "Hindi (हिन्दी)"
    assert resolve_language("What is the hallmarking fee?", "en") == "English"


def test_language_falls_back_to_script_when_unspecified():
    from rag.answer import resolve_language

    assert resolve_language("हॉलमार्किंग शुल्क क्या है?", None) == "Hindi (हिन्दी)"
    assert resolve_language("What is the fee?", None) == "English"


def test_unknown_language_code_falls_back_safely():
    from rag.answer import resolve_language

    assert resolve_language("What is the fee?", "klingon") == "English"
    assert resolve_language("What is the fee?", "") == "English"


def test_requested_language_reaches_the_prompt(monkeypatch):
    """The chosen language must actually be in the system prompt sent out."""
    seen = {}

    def capture(messages, **k):
        seen["system"] = messages[0]["content"]
        return answer_mod.llm.LLMResponse("शुल्क अनुसूची IV में दिया गया है। [S1]", "m")

    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(answer_mod.llm, "chat", capture)

    answer_question("What is the hallmarking fee?", language="hi")
    assert "Hindi" in seen["system"]


def test_extractive_framing_is_translated(monkeypatch):
    """Only the framing — the quoted legal text itself stays verbatim."""
    source = "The hallmarking fee shall be as specified in Schedule IV."
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit(text=source)])

    result = answer_question("hallmarking fee", offline=True, language="hi")
    assert "आधिकारिक बीआईएस दस्तावेज़ों" in result.text   # framing translated
    assert source in result.text                          # source untouched


def test_validate_extracts_unique_sorted_citations():
    text, cited, invalid = _validate("A [S2] B [S1] C [S2]", 3)
    assert cited == [1, 2] and invalid == []


def test_validate_flags_out_of_range_citations():
    _, cited, invalid = _validate("A [S1] B [S9] C [S0]", 3)
    assert cited == [1] and invalid == [0, 9]


def test_sources_block_names_a_verifiable_location():
    block = format_sources([make_hit()])
    assert "[S1]" in block
    assert "07_HALLMARKING/REGULATIONS/x.pdf" in block
    assert "page 12" in block


def test_prompt_forbids_outside_knowledge():
    prompt = answer_mod.SYSTEM_PROMPT.lower()
    assert "only" in prompt
    assert "never invent" in prompt


def test_answer_dataclass_defaults_are_safe():
    a = Answer(text="", hits=[], cited=[], grounded=False, refused=True)
    assert a.sources == [] and a.invalid_citations == []
