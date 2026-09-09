"""Decoder for BIS marks, licence numbers and standard references.

This checks the SHAPE of an identifier and explains what that kind of mark
means. It cannot and does not check whether a particular number was ever
issued, or is still live — that requires BIS's own registry, which this
system has no access to. Every result says so, and points at the official
portal where a real check can be made.

The distinction matters more here than it might elsewhere. A tool that told
someone a counterfeit licence number "looks valid" would be actively harmful:
it would launder a fake into a reassurance. So the wording throughout is
"matches the published format", never "is genuine".

Formats are taken from the corpus rather than assumed:
  * HUID — "six-digit alphanumeric", per the jeweller guidelines
    (07_HALLMARKING/JEWELLERS/Revised-Guidelines-for-JEWELLERS-Jan-24.pdf p.4)
  * CM/L — a real licence number appears in a BIS public recall notice as
    "CM/L 6300082303" (09_CONSUMER/.../Public-alert-for-product-recall...pdf p.1)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VERIFY_PORTALS = {
    "licence": ("BIS Care app / manakonline.in", "https://www.manakonline.in"),
    "hallmark": ("BIS Care app — 'Verify HUID'", "https://www.bis.gov.in"),
    "crs": ("BIS CRS portal", "https://www.crsbis.in"),
    "standard": ("BIS Standards catalogue", "https://standards.bis.gov.in"),
}


@dataclass
class MarkResult:
    input: str
    kind: str                 # licence | hallmark | crs | standard | unknown
    recognised: bool
    label: str                # short human name for this kind of identifier
    explanation: str
    format_note: str = ""
    caution: str = ""
    verify_at: tuple[str, str] | None = None
    search_hint: str = ""     # a query that finds the governing documents
    warnings: list[str] = field(default_factory=list)


# "CM/L-6300082303", "CM/L 6300082303", "CML6300082303"
CM_L = re.compile(r"^\s*CM\s*/?\s*L\s*[-–/]?\s*(\d{6,12})\s*$", re.IGNORECASE)
# HUID: exactly six alphanumeric characters.
HUID = re.compile(r"^\s*([A-Z0-9]{6})\s*$", re.IGNORECASE)
# "IS 17440", "IS 17440:2020", "IS/IEC 62368-1"
IS_REF = re.compile(
    r"^\s*IS\s*(?:/\s*(?:IEC|ISO|EN))?\s*:?\s*\d{2,5}"
    r"(?:\s*[-–]\s*\d{1,2})?(?:\s*\(?\s*Part\s*\d+\s*\)?)?(?:\s*[:\-]\s*(?:19|20)\d{2})?\s*$",
    re.IGNORECASE,
)
# CRS registration numbers are commonly written "R-1234567890".
CRS_REF = re.compile(r"^\s*R\s*[-–]\s*(\d{6,12})\s*$", re.IGNORECASE)

_CANNOT_VERIFY = (
    "This is a format check only. It does not confirm that the number was "
    "issued, is currently valid, or covers the product it appears on — that "
    "can only be confirmed against BIS's own registry."
)


def decode(value: str) -> MarkResult:
    raw = (value or "").strip()
    if not raw:
        return MarkResult(
            input=raw, kind="unknown", recognised=False, label="Nothing entered",
            explanation="Enter a BIS licence number, a HUID from a hallmark, or an IS standard number.",
        )

    m = CM_L.match(raw)
    if m:
        digits = m.group(1)
        result = MarkResult(
            input=raw, kind="licence", recognised=True,
            label="BIS Product Certification Licence (ISI Mark)",
            explanation=(
                "A CM/L number identifies a licence to apply the ISI Mark to a "
                "specific product made at a specific factory. The licence is "
                "tied to one Indian Standard and one manufacturing location — "
                "it does not cover a company's whole product range."
            ),
            format_note=f"Matches the CM/L format, with {len(digits)} digits.",
            caution=_CANNOT_VERIFY,
            verify_at=VERIFY_PORTALS["licence"],
            search_hint="ISI mark licence grant conditions product certification",
        )
        if len(digits) != 10:
            result.warnings.append(
                f"Licence numbers seen in BIS notices carry 10 digits; this has {len(digits)}. "
                "Worth double-checking against the source."
            )
        return result

    if CRS_REF.match(raw):
        return MarkResult(
            input=raw, kind="crs", recognised=True,
            label="CRS Registration Number (Compulsory Registration Scheme)",
            explanation=(
                "CRS registration covers electronics and IT goods notified under "
                "the Compulsory Registration Order. The manufacturer self-declares "
                "conformity on the basis of a test report from a BIS-recognised "
                "laboratory, rather than holding a factory-inspection licence."
            ),
            format_note="Matches the 'R-' registration number shape.",
            caution=(
                _CANNOT_VERIFY + " The CRS number format is not documented in the "
                "indexed corpus, so this shape check is weaker than the others here."
            ),
            verify_at=VERIFY_PORTALS["crs"],
            search_hint="compulsory registration scheme CRS registration validity",
        )

    if IS_REF.match(raw):
        return MarkResult(
            input=raw, kind="standard", recognised=True,
            label="Indian Standard number",
            explanation=(
                "This is a standard, not a licence. It specifies the requirements "
                "a product must meet. A product carrying the ISI Mark should show "
                "the IS number it was certified against, alongside the CM/L licence "
                "number."
            ),
            format_note="Matches the IS reference format.",
            verify_at=VERIFY_PORTALS["standard"],
            search_hint=raw,
        )

    m = HUID.match(raw)
    if m and any(ch.isdigit() for ch in m.group(1)):
        return MarkResult(
            input=raw, kind="hallmark", recognised=True,
            label="HUID (Hallmark Unique Identification)",
            explanation=(
                "A HUID is stamped on each hallmarked gold article. The full "
                "hallmark also carries the BIS mark, the purity/fineness grade, "
                "and the HUID itself. Each article gets its own HUID, so the same "
                "code should not appear on two pieces."
            ),
            format_note="Six alphanumeric characters, matching the published HUID format.",
            caution=(
                _CANNOT_VERIFY + " Use the BIS Care app to check what article a "
                "HUID was actually issued against."
            ),
            verify_at=VERIFY_PORTALS["hallmark"],
            search_hint="HUID hallmarking jewellery requirements",
        )

    return MarkResult(
        input=raw, kind="unknown", recognised=False,
        label="Not a recognised BIS identifier format",
        explanation=(
            "This does not match a BIS licence number (CM/L…), a six-character "
            "HUID, a CRS registration (R-…), or an Indian Standard number (IS …). "
            "It may still be valid — this tool only knows the formats documented "
            "in the indexed BIS material. Check the number against the marking on "
            "the product itself."
        ),
        caution="Not matching a known format is not proof that something is fake.",
        search_hint=raw,
    )
