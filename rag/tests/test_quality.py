"""The quality gate is the thing standing between corrupted PDF text and the
index, so every case here is a real string sampled from the BIS corpus rather
than a synthetic example."""

from __future__ import annotations

import pytest

from rag.quality import Script, Verdict, assess_line, classify_script, clean_page

GOOD_ENGLISH = [
    "Provided also that nothing in this order shall apply for 200 numbers of goods "
    "or articles imported for the purpose of research and development",
    "An Act to provide for the establishment of a national standards body for the "
    "harmonious development of the activities of standardisation",
    "The date of manufacturing for domestically produced goods and date of landing "
    "of consignments in India for goods manufactured overseas would apply",
    "THE GAZETTE OF INDIA : EXTRAORDINARY [PART II-SEC. 3(ii)]",
    "No. 228] NEW DELHI, THURSDAY, JUNE 14, 2018",
    "The registered jeweller shall submit the precious metal articles to the "
    "assaying and hallmarking centre with a request for hallmarking",
]

# Legacy non-Unicode Devanagari fonts decoded as Latin.
KRUTIDEV = [
    "jftLVªh laö Mhö ,yö&33004@99 REGD. NO. D. L.-33004/99 vlk/kj.k EXTRAORDINARY",
    "Hkkx III—[k.M 4 PART III—Section 4 izkf/dkj ls izdkf'kr PUBLISHED BY AUTHORITY",
    'la- 228] ubZ fnYyh] c`gLifrokj] twu 14] 2018@T;s"B 24] 1940',
]

GOOD_HINDI = [
    "असाधारण EXTRAORDINARY भाग II—खण् ड 3—उप-खण् ड (ii) PART II—Section 3—Sub-section (ii)",
    "वाजणज्य एवं उद्योग मंत्रालय (उद्योग संवधधन और आंतररक व् यापार जवभाग) आदेि नई ददल्ली",
]

# Broken glyph maps: stranded consonants, spliced fragments, repeats, and
# Latin/bracket characters welded into Devanagari words.
BROKEN_HINDI = [
    "केन्‍द रीय सरक र क , भ तीय सरक म नक ब् य सरकू अधिननय सरकम, 2016 (2016 क 11) की ि 38",
    "(ि) “अनएज्ञ्तति ी’’ रे र व् य सरक्तित असभप्रेत ुै ्िरे इर अधिननय सरकम के अिीन अनएज्ञ्तत दी ुै",
    "अयाय अयाय अयाय अयाय 1 रिज ीकरण माण रिज ीकरण माण रिज ीकरण माण",
    "9) असेZयग और हॉलमा[कग क,\\ आभूषणिव ेता से अनुसूची- IV म, िन-दw ट हॉलमा[कग फस लेगा",
]


@pytest.mark.parametrize("text", GOOD_ENGLISH)
def test_real_english_is_kept(text):
    assert assess_line(text).verdict is Verdict.KEEP


@pytest.mark.parametrize("text", GOOD_HINDI)
def test_readable_hindi_is_kept(text):
    assert assess_line(text).verdict is Verdict.KEEP


@pytest.mark.parametrize("text", KRUTIDEV)
def test_legacy_font_gibberish_is_rejected(text):
    a = assess_line(text)
    assert a.verdict is Verdict.REJECT
    assert "gibberish" in a.reason


@pytest.mark.parametrize("text", BROKEN_HINDI)
def test_corrupted_devanagari_is_rejected(text):
    a = assess_line(text)
    assert a.verdict is Verdict.REJECT
    assert "corruption" in a.reason


def test_unmapped_glyph_escapes_are_rejected():
    a = assess_line("/uni0909/uni092A/uni092D/uni094B/g6989 /uni0924/uni093E")
    assert a.verdict is Verdict.REJECT
    assert a.reason == "unmapped glyph escapes"


def test_cid_escapes_are_rejected():
    assert assess_line("(cid:123)(cid:45) some text here").verdict is Verdict.REJECT


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Bureau of Indian Standards", Script.LATIN),
        ("भारतीय मानक ब्यूरो अधिनियम", Script.DEVANAGARI),
        ("1234 -- ... 5678", Script.NEUTRAL),
    ],
)
def test_script_classification(text, expected):
    assert classify_script(text) is expected


def test_roman_numerals_do_not_trigger_the_vowel_heuristic():
    # "III"/"XIV" have no vowels but are legitimate in gazette headings.
    assert assess_line("PART III SEC XIV of the said Act shall apply").verdict is Verdict.KEEP


def test_clean_page_keeps_english_and_drops_corrupt_hindi():
    page = "\n".join([GOOD_ENGLISH[0], BROKEN_HINDI[0], GOOD_ENGLISH[1], KRUTIDEV[0]])
    result = clean_page(page)
    assert result.kept_lines == 2
    assert result.dropped_lines == 2
    assert GOOD_ENGLISH[0] in result.kept_text
    assert "सरक" not in result.kept_text
    assert "jftLVªh" not in result.kept_text


def test_clean_page_reports_why_lines_were_dropped():
    result = clean_page("\n".join(BROKEN_HINDI))
    assert result.dropped_lines == len(BROKEN_HINDI)
    assert result.drop_ratio == 1.0
    assert sum(result.dropped_reasons.values()) == len(BROKEN_HINDI)


def test_empty_and_whitespace_pages_are_safe():
    for text in ("", "   ", "\n\n\n"):
        assert clean_page(text).kept_text == ""
