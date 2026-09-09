"""Text quality gate for the BIS corpus.

Many BIS gazette PDFs carry text that *extracts* without error but is not
actually readable: the PDF embeds a legacy non-Unicode Devanagari font
(Krutidev/ISCII), so "रजिस्ट्री सं." comes out as "jftLVªh laö", or the
font's glyph->Unicode map is broken, so real Devanagari decodes with spurious
syllables spliced in ("केन्‍द रीय सरक र क" for "केन्द्रीय सरकार का").

Indexing that text is worse than not indexing it: it is unsearchable, and if
it ever reaches an answer it looks like authoritative legal text while being
gibberish. So every line is classified and scored before it can enter the
index, and rejected lines are recorded with a reason so the drop is auditable
rather than silent.

The gate is deliberately strict on Devanagari and permissive on English: the
English half of a bilingual gazette extracts cleanly and is the operative
legal text we ground answers on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LATIN = re.compile(r"[A-Za-z]")
# PDF text extractors emit these when a glyph has no Unicode mapping at all.
UNMAPPED_GLYPH = re.compile(r"/uni[0-9A-Fa-f]{4}|/g\d+|\(cid:\d+\)")

# Devanagari combining marks (matras, virama, nukta, anusvara...). A cluster
# of these with no preceding consonant is a decoding artifact, not text.
DEV_COMBINING = re.compile(r"[ऺ-ॏ॑-ॗॢॣ]")
DEV_CONSONANT = re.compile(r"[क-हक़-य़ॸ-ॿ]")

# High-frequency English function words. Real English prose in this corpus is
# dense with them; legacy-font gibberish has essentially none.
ENGLISH_STOPWORDS = frozenset("""
a an and any are as at be been by for from has have in is it its may no not
of on or shall should such that the this to under upon was were which with
will would where when who whom been being do does under provided section rule
order act said there their they these those than then if all also
""".split())

# Words that legitimately appear in BIS English text with no vowel-rich shape,
# so the vowel heuristic does not penalise them.
_ALLOWED_SHORT = frozenset({"is", "of", "in", "to", "by", "no", "or", "as", "at", "on", "if", "it"})

_ROMAN = re.compile(r"^[IVXLCDMivxlcdm]+$")
# An uppercase letter in the middle of an otherwise lowercase word is a
# Krutidev signature ("jftLVªh", "izdkf'kr"); English words never do this.
_INTERNAL_CAPS = re.compile(r"[a-z][A-Z]")
# Punctuation or a Latin letter wedged between two Devanagari characters is
# unambiguous glyph-map damage ("हॉलमा[कग", "असेZयग").
_DEV_INTRUSION = re.compile(r"[ऀ-ॿ][\[\]\\/{}<>@#$%^&*|~`A-Za-z][ऀ-ॿ]")


class Script(str, Enum):
    LATIN = "latin"
    DEVANAGARI = "devanagari"
    NEUTRAL = "neutral"  # digits, punctuation, whitespace only
    MIXED = "mixed"


class Verdict(str, Enum):
    KEEP = "keep"
    REJECT = "reject"


@dataclass(frozen=True)
class LineAssessment:
    text: str
    script: Script
    verdict: Verdict
    score: float
    reason: str

    @property
    def kept(self) -> bool:
        return self.verdict is Verdict.KEEP


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^\wऀ-ॿ]+", text) if t]


def classify_script(text: str) -> Script:
    dev = len(DEVANAGARI.findall(text))
    lat = len(LATIN.findall(text))
    if dev == 0 and lat == 0:
        return Script.NEUTRAL
    if dev == 0:
        return Script.LATIN
    if lat == 0:
        return Script.DEVANAGARI
    # Bilingual gazette headers routinely put both scripts on one line
    # ("असाधारण EXTRAORDINARY"). That is legitimate, so only call it MIXED
    # when neither script clearly dominates.
    total = dev + lat
    if dev / total >= 0.75:
        return Script.DEVANAGARI
    if lat / total >= 0.75:
        return Script.LATIN
    return Script.MIXED


def score_latin(text: str) -> tuple[float, str]:
    """Return (quality 0..1, reason). Detects legacy-font Devanagari that
    decoded into Latin gibberish such as "jftLVªh laö Mhö ,yö"."""
    toks = [t.lower() for t in _tokens(text) if LATIN.search(t)]
    if not toks:
        return 1.0, "no latin words to judge"

    stop_hits = sum(1 for t in toks if t in ENGLISH_STOPWORDS)
    # English words essentially always contain a vowel; Krutidev output
    # ("jftLVªh", "vlk", "Hkkx", "[k.M") frequently does not.
    voweled = sum(1 for t in toks if re.search(r"[aeiouy]", t) or t in _ALLOWED_SHORT)
    vowel_ratio = voweled / len(toks)

    # Letters from the Latin-1 supplement block used *inside* words are a
    # strong Krutidev signature (ª in "jftLVªh", ö in "laö").
    exotic = sum(
        1
        for ch in text
        if LATIN.search(ch) is None
        and ch.isalpha()
        and not DEVANAGARI.match(ch)
        and unicodedata.category(ch).startswith("L")
    )
    exotic_ratio = exotic / max(len(text), 1)

    # Tokens of real length carrying no vowel at all ("Hkkx", "dkj", "[k.M").
    # Roman numerals are excluded — "III" and "XIV" are legitimate here.
    judged = [t for t in toks if len(t) >= 3 and not _ROMAN.match(t)]
    novowel = sum(1 for t in judged if not re.search(r"[aeiouy]", t))
    novowel_ratio = novowel / len(judged) if judged else 0.0

    internal_caps = sum(1 for t in _tokens(text) if _INTERNAL_CAPS.search(t))
    caps_ratio = internal_caps / len(toks)

    score = vowel_ratio
    if len(toks) >= 6 and stop_hits == 0:
        # A long run of English with no function word at all is not prose.
        score -= 0.35
    if exotic_ratio > 0.01:
        score -= 0.30
    if novowel_ratio > 0.15:
        score -= min(0.6, novowel_ratio * 1.6)
    if caps_ratio > 0.05:
        score -= 0.35
    score = max(0.0, min(1.0, score))

    if score < 0.55:
        return score, (
            f"latin gibberish (vowel_ratio={vowel_ratio:.2f}, "
            f"stopwords={stop_hits}, novowel={novowel_ratio:.2f}, "
            f"internal_caps={caps_ratio:.2f}, exotic={exotic_ratio:.3f}) "
            "— likely legacy non-Unicode Devanagari font"
        )
    return score, "ok"


def score_devanagari(text: str) -> tuple[float, str]:
    """Return (quality 0..1, reason). Detects broken glyph maps that splice
    spurious syllables into real Hindi, and Latin letters fused into
    Devanagari words ("हॉलमा[कग")."""
    toks = [t for t in _tokens(text) if DEVANAGARI.search(t)]
    if not toks:
        return 1.0, "no devanagari words to judge"

    penalties: list[str] = []
    score = 1.0

    # 1. Latin letters welded inside a Devanagari token: always corruption.
    fused = sum(1 for t in toks if DEVANAGARI.search(t) and LATIN.search(t))
    fused_ratio = fused / len(toks)
    if fused_ratio > 0.05:
        score -= min(0.6, fused_ratio * 3)
        penalties.append(f"latin-fused words {fused_ratio:.2f}")

    # 1b. A stray bracket/slash/Latin letter sitting *between* two Devanagari
    #     characters is unambiguous damage, so even one occurrence counts.
    intrusions = len(_DEV_INTRUSION.findall(text))
    if intrusions:
        score -= min(0.6, 0.25 + 0.15 * intrusions)
        penalties.append(f"intruding glyphs {intrusions}")

    # 1c. A broken map strands lone consonants where whole syllables belong
    #     ("केन्‍द रीय सरक र क , भ तीय"). Standalone one-character words are
    #     rare in Hindi, so a high proportion of them means dropped glyphs.
    singles = sum(1 for t in toks if len(t) == 1)
    single_ratio = singles / len(toks)
    if len(toks) >= 8 and single_ratio > 0.20:
        score -= min(0.6, single_ratio * 1.5)
        penalties.append(f"stranded single chars {single_ratio:.2f}")

    # 2. The same token repeated back-to-back many times is a rendering
    #    artifact ("अयाय अयाय अयाय अयाय"), not Hindi.
    runs = 0
    for i in range(1, len(toks)):
        if toks[i] == toks[i - 1] and len(toks[i]) > 1:
            runs += 1
    run_ratio = runs / max(len(toks) - 1, 1)
    if run_ratio > 0.12:
        score -= min(0.5, run_ratio * 2)
        penalties.append(f"repeated-token runs {run_ratio:.2f}")

    # 3. Orphan combining marks — a matra/virama with no consonant to attach
    #    to means the glyph map dropped the base character.
    orphans = 0
    for i, ch in enumerate(text):
        if DEV_COMBINING.match(ch):
            prev = text[i - 1] if i else ""
            if not (DEV_CONSONANT.match(prev) or DEV_COMBINING.match(prev)):
                orphans += 1
    dev_chars = len(DEVANAGARI.findall(text))
    orphan_ratio = orphans / max(dev_chars, 1)
    if orphan_ratio > 0.04:
        score -= min(0.5, orphan_ratio * 5)
        penalties.append(f"orphan matras {orphan_ratio:.2f}")

    # 4. A broken map tends to emit the *same* short fragment over and over
    #    across the line ("सरक" spliced into every word).
    if len(toks) >= 8:
        short = [t for t in toks if 2 <= len(t) <= 4]
        if short:
            most = max(set(short), key=short.count)
            rep = short.count(most) / len(toks)
            if rep > 0.22:
                score -= min(0.5, rep)
                penalties.append(f"fragment '{most}' repeats {rep:.2f}")

    score = max(0.0, min(1.0, score))
    if score < 0.6:
        return score, "devanagari corruption (" + "; ".join(penalties) + ")"
    return score, "ok"


def assess_line(text: str, *, min_chars: int = 3) -> LineAssessment:
    stripped = text.strip()
    if len(stripped) < min_chars:
        return LineAssessment(text, Script.NEUTRAL, Verdict.REJECT, 0.0, "too short")

    if UNMAPPED_GLYPH.search(stripped):
        return LineAssessment(
            text, classify_script(stripped), Verdict.REJECT, 0.0, "unmapped glyph escapes"
        )

    script = classify_script(stripped)
    if script is Script.NEUTRAL:
        return LineAssessment(text, script, Verdict.REJECT, 0.0, "no letters")

    if script is Script.LATIN:
        score, reason = score_latin(stripped)
    elif script is Script.DEVANAGARI:
        score, reason = score_devanagari(stripped)
    else:  # MIXED — both halves must hold up
        ls, lr = score_latin(stripped)
        ds, dr = score_devanagari(stripped)
        score = min(ls, ds)
        reason = lr if ls <= ds else dr

    verdict = Verdict.KEEP if score >= 0.6 else Verdict.REJECT
    return LineAssessment(text, script, verdict, score, reason)


@dataclass
class PageQuality:
    kept_text: str
    kept_lines: int
    dropped_lines: int
    dropped_reasons: dict[str, int]
    scripts: dict[str, int]

    @property
    def drop_ratio(self) -> float:
        total = self.kept_lines + self.dropped_lines
        return self.dropped_lines / total if total else 0.0


def clean_page(raw_text: str) -> PageQuality:
    """Filter a page down to lines that are genuinely readable."""
    kept: list[str] = []
    dropped_reasons: dict[str, int] = {}
    scripts: dict[str, int] = {}
    dropped = 0

    for line in raw_text.splitlines():
        a = assess_line(line)
        if a.kept:
            kept.append(line.strip())
            scripts[a.script.value] = scripts.get(a.script.value, 0) + 1
        else:
            dropped += 1
            key = a.reason.split("(")[0].strip()
            dropped_reasons[key] = dropped_reasons.get(key, 0) + 1

    return PageQuality(
        kept_text="\n".join(kept),
        kept_lines=len(kept),
        dropped_lines=dropped,
        dropped_reasons=dropped_reasons,
        scripts=scripts,
    )
