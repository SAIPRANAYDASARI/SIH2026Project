"""Certification pathway finder.

"Which BIS scheme applies to me?" is the first question a manufacturer has,
and getting it wrong wastes months: an electronics importer who files for an
ISI licence has applied under the wrong scheme entirely.

The routing itself is a small decision tree over facts the user supplies —
where they manufacture, what they make, whether the product is under a QCO.
The tree decides only WHICH scheme applies. Everything substantive about that
scheme (what to submit, what the process involves) is retrieved from the
indexed BIS documents and cited, so the advice is checkable rather than
hard-coded folklore that silently rots as rules change.

Where the corpus cannot support a step, the step says so instead of being
filled in from memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rag.search import Mode, search


@dataclass
class Question:
    key: str
    prompt_en: str
    prompt_hi: str
    options: list[tuple[str, str, str]]  # (value, label_en, label_hi)


QUESTIONS = [
    Question(
        key="location",
        prompt_en="Where is the product manufactured?",
        prompt_hi="उत्पाद का विनिर्माण कहाँ होता है?",
        options=[
            ("india", "In India", "भारत में"),
            ("abroad", "Outside India", "भारत के बाहर"),
        ],
    ),
    Question(
        key="category",
        prompt_en="What kind of product is it?",
        prompt_hi="यह किस प्रकार का उत्पाद है?",
        options=[
            ("electronics", "Electronics / IT goods", "इलेक्ट्रॉनिक्स / आईटी सामान"),
            ("jewellery", "Gold jewellery or artefacts", "सोने के आभूषण या कलाकृतियाँ"),
            ("other", "Any other product", "कोई अन्य उत्पाद"),
        ],
    ),
]


@dataclass
class PathwayStep:
    title: str
    detail: str
    citations: list[dict] = field(default_factory=list)


@dataclass
class Pathway:
    scheme: str
    scheme_code: str
    summary: str
    why: str
    steps: list[PathwayStep] = field(default_factory=list)
    caveat: str = ""


# Each route names the scheme and the query used to pull its real requirements
# out of the corpus. The queries are deliberately phrased the way the source
# documents are, not the way a user would ask.
_ROUTES = {
    ("abroad", "electronics"): (
        "Compulsory Registration Scheme (CRS)",
        "CRS",
        "Electronics and IT goods notified under the Compulsory Registration Order require "
        "registration with BIS before they can be sold in India, whether made in India or imported.",
        [
            ("Confirm the product is notified under CRS",
             "which products require compulsory registration electronics IT goods"),
            ("Get the product tested at a BIS-recognised laboratory",
             "CRS registration test report BIS recognised laboratory"),
            ("Apply for registration and understand its validity",
             "CRS registration application validity renewal two years"),
        ],
    ),
    ("india", "electronics"): (
        "Compulsory Registration Scheme (CRS)",
        "CRS",
        "Electronics and IT goods notified under the Compulsory Registration Order require "
        "registration with BIS before sale in India.",
        [
            ("Confirm the product is notified under CRS",
             "which products require compulsory registration electronics IT goods"),
            ("Get the product tested at a BIS-recognised laboratory",
             "CRS registration test report BIS recognised laboratory"),
            ("Apply for registration and understand its validity",
             "CRS registration application validity renewal two years"),
        ],
    ),
    ("abroad", "other"): (
        "Foreign Manufacturers Certification Scheme (FMCS)",
        "FMCS",
        "A manufacturer located outside India applies under FMCS to use the ISI Mark on goods "
        "sold in India. It requires a nominated Indian representative.",
        [
            ("Prepare the application and supporting documents",
             "foreign manufacturer certification scheme application checklist documents"),
            ("Nominate an authorised Indian representative",
             "authorised Indian representative foreign manufacturer responsibilities"),
            ("Factory inspection and product testing",
             "factory inspection testing grant of licence foreign manufacturer"),
        ],
    ),
    ("india", "other"): (
        "Product Certification Scheme (ISI Mark)",
        "ISI",
        "A domestic manufacturer applies for a licence to apply the ISI Mark against the "
        "relevant Indian Standard for the product and factory.",
        [
            ("Identify the Indian Standard for your product",
             "grant of licence application relevant Indian Standard product certification"),
            ("Apply for the licence and prepare for inspection",
             "application for grant of licence Standard Mark scheme process fee"),
            ("Maintain in-house testing and records",
             "in-house test facilities quality control records licensee obligations"),
        ],
    ),
    ("abroad", "jewellery"): (
        "Hallmarking registration",
        "HALLMARK",
        "Gold jewellery sold in India must be hallmarked. A jeweller must register with BIS, "
        "and articles are hallmarked at a recognised Assaying and Hallmarking Centre.",
        [
            ("Register as a jeweller with BIS",
             "jeweller registration hallmarking requirements"),
            ("Understand HUID and the hallmark components",
             "HUID hallmark BIS mark purity grade jewellery"),
            ("Hallmarking at a recognised centre and its fees",
             "assaying hallmarking centre fee jeweller"),
        ],
    ),
}
_ROUTES[("india", "jewellery")] = _ROUTES[("abroad", "jewellery")]


class IncompleteAnswers(ValueError):
    """Not enough was answered to route to a scheme."""


def find_pathway(answers: dict, *, language: str = "en", top_k: int = 3) -> Pathway:
    """Route to a scheme, then fill each step from the indexed documents.

    Every question must be answered. Defaulting a missing answer would hand
    someone a confident "the ISI Mark scheme applies to you" derived from
    nothing they told us — the sort of plausible, unfounded advice this
    system exists to avoid.
    """
    missing = [q.key for q in QUESTIONS if not (answers or {}).get(q.key)]
    if missing:
        raise IncompleteAnswers(
            "Answer all questions before a scheme can be identified. "
            f"Missing: {', '.join(missing)}"
        )

    valid = {q.key: {v for v, _, _ in q.options} for q in QUESTIONS}
    for key, allowed in valid.items():
        if str(answers[key]).lower() not in allowed:
            raise IncompleteAnswers(
                f"'{answers[key]}' is not a recognised option for '{key}'."
            )

    location = str(answers["location"]).lower()
    category = str(answers["category"]).lower()

    route = _ROUTES.get((location, category)) or _ROUTES[("india", "other")]
    scheme, code, summary, step_specs = route

    why = {
        "CRS": "Electronics and IT goods are handled under CRS rather than the ISI Mark scheme.",
        "FMCS": "The manufacturing site is outside India, which is what FMCS exists for.",
        "ISI": "A product made in India that is not electronics or jewellery falls under the "
               "standard product certification route.",
        "HALLMARK": "Gold articles are covered by hallmarking rather than product certification.",
    }[code]

    steps: list[PathwayStep] = []
    for title, query in step_specs:
        hits = search(query, mode=Mode.HYBRID, top_k=top_k)
        citations = [
            {
                "document": h.relpath,
                "page": h.page_number,
                "title": h.title,
                "text": h.text[:600],
            }
            for h in hits[:top_k]
        ]
        detail = (
            "See the cited passages for the exact requirements."
            if citations
            else "The indexed documents do not cover this step — check bis.gov.in."
        )
        steps.append(PathwayStep(title=title, detail=detail, citations=citations))

    return Pathway(
        scheme=scheme,
        scheme_code=code,
        summary=summary,
        why=why,
        steps=steps,
        caveat=(
            "This routes you to the scheme that normally applies to the answers you gave. "
            "Product-specific Quality Control Orders can change the picture, so confirm "
            "against the cited documents and with BIS before you file."
        ),
    )
