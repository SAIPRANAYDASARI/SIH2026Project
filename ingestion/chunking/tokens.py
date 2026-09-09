"""Token counting.

Uses whitespace word count as an approximation of BGE-M3/BPE token count
rather than a real tokenizer, to avoid a heavy dependency (tiktoken bundles
a vocab file normally fetched from a CDN at import time, which is a bad fit
for an offline-capable, network-restricted deployment target). Whitespace
tokens run roughly 1.3x actual BPE tokens for English prose, so the target
range below is scaled accordingly. This is a real trade-off, not a shortcut
taken silently — see docs/DECISIONS.md.
"""

from __future__ import annotations

# Empirical-ish scaling: BPE tokens ≈ 1.3 × whitespace words for English/BIS
# technical prose. Target 400-800 *tokens* becomes ~310-615 *words* here.
_WORDS_PER_TOKEN = 1 / 1.3

TARGET_MIN_TOKENS = 400
TARGET_MAX_TOKENS = 800
OVERLAP_RATIO = 0.15


def approx_token_count(text: str) -> int:
    word_count = len(text.split())
    return round(word_count / _WORDS_PER_TOKEN)


def target_min_words() -> int:
    return round(TARGET_MIN_TOKENS * _WORDS_PER_TOKEN)


def target_max_words() -> int:
    return round(TARGET_MAX_TOKENS * _WORDS_PER_TOKEN)


def overlap_word_count() -> int:
    return round(target_max_words() * OVERLAP_RATIO)
