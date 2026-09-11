"""Certification pathway finder, split by sector.

"Which BIS scheme applies to me?" is the first question anyone has, and
getting it wrong wastes months: an electronics importer who files for an ISI
licence has applied under the wrong scheme entirely.

Two audiences ask it for different reasons, so the tree asks a sector first:

  industrial — a company that makes, imports or exports goods. It needs the
               scheme, the licence route, and (because the answer genuinely
               differs) whether it manufactures inside India or outside it.
  consumer   — a person buying goods, who needs to know whether a product is
               required to carry a mark and what to do when it does not.

The routing itself is a small decision tree over facts the user supplies.
The tree decides only WHICH route applies. Everything substantive about that
route is retrieved from the indexed BIS documents and cited, so the advice is
checkable rather than hard-coded folklore that silently rots as rules change.

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
    # Only asked when another answer has one of these values. Asking a
    # consumer where their factory is would be nonsense, and a question that
    # cannot apply is worse than no question: it invites a wrong answer.
    show_when: dict[str, list[str]] | None = None


# Industries are the ones this corpus can actually speak to: the products
# carrying Quality Control Orders, plus the two schemes that exist separately
# (hallmarking for gold, CRS for electronics). Offering an industry the
# documents say nothing about would produce a confident, empty pathway.
INDUSTRIES = [
    ("gold", "Gold & Jewellery", "सोना और आभूषण"),
    ("electronics", "Electronics & IT Goods", "इलेक्ट्रॉनिक्स और आईटी सामान"),
    ("electrical", "Electrical Equipment & Appliances", "विद्युत उपकरण"),
    ("chemicals", "Chemicals & Petrochemicals", "रसायन और पेट्रो रसायन"),
    ("steel", "Steel & Metals", "इस्पात और धातु"),
    ("textiles", "Textiles & Medical Textiles", "वस्त्र और चिकित्सा वस्त्र"),
    ("footwear", "Footwear & Leather", "जूते और चमड़ा"),
    ("glass", "Safety Glass & Construction", "सुरक्षा कांच और निर्माण"),
    ("other", "Any other product", "कोई अन्य उत्पाद"),
]


QUESTIONS = [
    Question(
        key="sector",
        prompt_en="Who is asking?",
        prompt_hi="कौन पूछ रहा है?",
        options=[
            ("industrial", "A company / manufacturer", "कंपनी / निर्माता"),
            ("consumer", "A consumer / buyer", "उपभोक्ता / खरीदार"),
        ],
    ),
    Question(
        key="industry",
        prompt_en="Which industry is your product in?",
        prompt_hi="आपका उत्पाद किस उद्योग में है?",
        options=INDUSTRIES,
        show_when={"sector": ["industrial"]},
    ),
    Question(
        key="location",
        prompt_en="Where is the product manufactured?",
        prompt_hi="उत्पाद का विनिर्माण कहाँ होता है?",
        options=[
            ("india", "In India (Indian company)", "भारत में (भारतीय कंपनी)"),
            ("abroad", "Outside India (foreign company)", "भारत के बाहर (विदेशी कंपनी)"),
        ],
        show_when={"sector": ["industrial"]},
    ),
    Question(
        key="trade",
        prompt_en="What do you want to do with the goods?",
        prompt_hi="आप माल के साथ क्या करना चाहते हैं?",
        options=[
            ("domestic", "Sell within India", "भारत में बेचना"),
            ("import", "Import into India", "भारत में आयात करना"),
            ("export", "Export from India", "भारत से निर्यात करना"),
        ],
        show_when={"sector": ["industrial"]},
    ),
    Question(
        key="need",
        prompt_en="What do you want to know?",
        prompt_hi="आप क्या जानना चाहते हैं?",
        options=[
            ("required", "Must this product carry a BIS mark?", "क्या इस उत्पाद पर BIS चिह्न होना चाहिए?"),
            ("verify", "How do I check a mark is genuine?", "चिह्न असली है, कैसे जांचें?"),
            ("complaint", "How do I complain about a product?", "उत्पाद की शिकायत कैसे करें?"),
        ],
        show_when={"sector": ["consumer"]},
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
    sector: str = "industrial"


class IncompleteAnswers(ValueError):
    """Not enough was answered to route to a scheme."""


def visible_questions(answers: dict) -> list[Question]:
    """The questions that apply given what has been answered so far."""
    shown = []
    for q in QUESTIONS:
        if q.show_when is None:
            shown.append(q)
            continue
        if all(str((answers or {}).get(k, "")).lower() in vals
               for k, vals in q.show_when.items()):
            shown.append(q)
    return shown


# Step specs are (title, corpus query). The queries are deliberately phrased
# the way the source documents are, not the way a user would ask.
_ISI_STEPS = [
    ("Identify the Indian Standard for your product",
     "grant of licence application relevant Indian Standard product certification"),
    ("Apply for the licence and prepare for inspection",
     "application for grant of licence Standard Mark scheme process fee"),
    ("Maintain in-house testing and records",
     "in-house test facilities quality control records licensee obligations"),
]
_FMCS_STEPS = [
    ("Prepare the application and supporting documents",
     "foreign manufacturer certification scheme application checklist documents"),
    ("Nominate an authorised Indian representative",
     "authorised Indian representative foreign manufacturer responsibilities"),
    ("Factory inspection, testing and fees",
     "foreign manufacturers certification scheme fee factory inspection licence"),
]
_CRS_STEPS = [
    ("Confirm the product is notified under CRS",
     "which products require compulsory registration electronics IT goods"),
    ("Get the product tested at a BIS-recognised laboratory",
     "CRS registration test report BIS recognised laboratory"),
    ("Apply for registration and understand its validity",
     "CRS registration application validity renewal"),
]
_HALLMARK_STEPS = [
    ("Register as a jeweller with BIS",
     "jeweller registration hallmarking requirements"),
    ("Understand HUID and the hallmark components",
     "HUID hallmark BIS mark purity grade jewellery"),
    ("Hallmarking at a recognised centre and its fees",
     "assaying hallmarking centre fee jeweller"),
]
_IMPORT_STEPS = [
    ("Confirm whether the product carries a Quality Control Order",
     "Quality Control Order notified products compulsory use of Standard Mark"),
    ("A manufacturer outside India must hold a BIS licence before the goods are sold here",
     "manufacturer in foreign country required to obtain licence imported goods"),
    ("Apply under the scheme that fits the goods",
     "foreign manufacturer certification scheme application checklist documents"),
]
_EXPORT_STEPS = [
    ("Check the export carve-out in the Quality Control Order",
     "nothing in this Order shall apply to goods or articles meant for export"),
    ("Confirm the Order covering your specific product",
     "Quality Control Order notified products compulsory use of Standard Mark"),
    ("Certification you may still want for the buyer's market",
     "product certification scheme licence Indian Standard export"),
]
_CONSUMER_STEPS = {
    "required": [
        ("Products where a BIS mark is compulsory",
         "Quality Control Order notified products compulsory use of Standard Mark"),
        ("What the Standard Mark and hallmark actually certify",
         "Standard Mark hallmark conformity Indian Standard meaning"),
    ],
    "verify": [
        ("What a licence number and hallmark are made of",
         "HUID hallmark BIS mark purity licence number jewellery"),
        ("Checking a licence or registration against BIS records",
         "verify licence registration number BIS portal consumer"),
    ],
    "complaint": [
        ("How BIS handles consumer complaints",
         "consumer complaint grievance redressal BIS procedure"),
        ("Timelines and what BIS commits to",
         "citizens charter complaint timeline response BIS"),
    ],
}


def _route(sector: str, industry: str, location: str, trade: str, need: str):
    """Return (scheme, code, summary, why, steps)."""
    if sector == "consumer":
        titles = {
            "required": ("Is a BIS mark compulsory?", "CONSUMER-REQUIRED"),
            "verify": ("Checking a mark is genuine", "CONSUMER-VERIFY"),
            "complaint": ("Raising a complaint", "CONSUMER-COMPLAINT"),
        }
        scheme, code = titles[need]
        return (
            scheme, code,
            "Guidance for a buyer rather than a manufacturer, drawn from the indexed "
            "BIS consumer documents.",
            "You said you are asking as a consumer.",
            _CONSUMER_STEPS[need],
        )

    # ── industrial ───────────────────────────────────────────────────
    if trade == "export":
        return (
            "Export from India", "EXPORT",
            "Quality Control Orders generally carve out goods meant for export, so the "
            "compulsory Indian marking requirement usually does not bite on an export "
            "consignment. The destination country's own rules still apply, and BIS "
            "certification can still be worth holding for that buyer.",
            "You are exporting out of India, which the Orders treat differently from "
            "goods placed on the Indian market.",
            _EXPORT_STEPS,
        )

    if trade == "import" or location == "abroad":
        if industry == "electronics":
            return (
                "Compulsory Registration Scheme (CRS)", "CRS",
                "Electronics and IT goods notified under the Compulsory Registration Order "
                "require registration with BIS before sale in India — whether made in India "
                "or imported.",
                "Electronics and IT goods run through CRS, not the ISI Mark scheme, "
                "regardless of where they are made.",
                _CRS_STEPS,
            )
        if industry == "gold":
            return (
                "Hallmarking registration", "HALLMARK",
                "Gold articles sold in India must be hallmarked, and the seller must be "
                "registered with BIS.",
                "Gold is covered by hallmarking rather than product certification.",
                _HALLMARK_STEPS,
            )
        steps = _IMPORT_STEPS if trade == "import" else _FMCS_STEPS
        return (
            "Foreign Manufacturers Certification Scheme (FMCS)", "FMCS",
            "A manufacturer located outside India applies under FMCS to use the ISI Mark "
            "on goods sold in India. It requires a nominated Indian representative.",
            "The goods are made outside India, which is what FMCS exists for.",
            steps,
        )

    # domestic Indian manufacturer
    if industry == "electronics":
        return (
            "Compulsory Registration Scheme (CRS)", "CRS",
            "Electronics and IT goods notified under the Compulsory Registration Order "
            "require registration with BIS before sale in India.",
            "Electronics and IT goods run through CRS rather than the ISI Mark scheme.",
            _CRS_STEPS,
        )
    if industry == "gold":
        return (
            "Hallmarking registration", "HALLMARK",
            "Gold jewellery sold in India must be hallmarked. A jeweller registers with "
            "BIS, and articles are hallmarked at a recognised Assaying and Hallmarking "
            "Centre.",
            "Gold is covered by hallmarking rather than product certification.",
            _HALLMARK_STEPS,
        )
    return (
        "Product Certification Scheme (ISI Mark)", "ISI",
        "A domestic manufacturer applies for a licence to apply the ISI Mark against the "
        "relevant Indian Standard for the product and factory.",
        "A product made in India, outside the electronics and gold schemes, falls under "
        "the standard product certification route.",
        _ISI_STEPS,
    )


def find_pathway(answers: dict, *, language: str = "en", top_k: int = 3) -> Pathway:
    """Route to a scheme, then fill each step from the indexed documents.

    Every question that applies must be answered. Defaulting a missing answer
    would hand someone a confident "the ISI Mark scheme applies to you"
    derived from nothing they told us — the sort of plausible, unfounded
    advice this system exists to avoid.
    """
    answers = answers or {}
    needed = visible_questions(answers)
    missing = [q.key for q in needed if not answers.get(q.key)]
    if missing:
        raise IncompleteAnswers(
            "Answer all questions before a scheme can be identified. "
            f"Missing: {', '.join(missing)}"
        )

    for q in needed:
        allowed = {v for v, _, _ in q.options}
        if str(answers[q.key]).lower() not in allowed:
            raise IncompleteAnswers(
                f"'{answers[q.key]}' is not a recognised option for '{q.key}'."
            )

    get = lambda k: str(answers.get(k, "")).lower()  # noqa: E731
    sector = get("sector")
    scheme, code, summary, why, step_specs = _route(
        sector, get("industry"), get("location"), get("trade"), get("need")
    )

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

    caveat = (
        "This routes you to the scheme that normally applies to the answers you gave. "
        "Product-specific Quality Control Orders can change the picture, so confirm "
        "against the cited documents and with BIS before you file."
    )
    if code == "EXPORT":
        caveat = (
            "The export carve-out is written into each Order separately, so confirm it in "
            "the Order covering your product — and remember this says nothing about what "
            "the importing country requires, which is outside these documents entirely."
        )

    return Pathway(
        scheme=scheme,
        scheme_code=code,
        summary=summary,
        why=why,
        steps=steps,
        caveat=caveat,
        sector=sector or "industrial",
    )
