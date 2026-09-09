"""Domain gate: is this question Manak Sahayak's business at all?

The general-knowledge path exists so a user with a real compliance problem is
not left with a bare "not found". But it also made the assistant answer
anything — asked "who is Virat Kohli", it produced a full cricket biography
under a BIS banner. That is worse than unhelpful: an assistant that will
discuss anything reads as a generic chatbot wearing a government badge, and it
invites exactly the kind of trust it has not earned.

So off-domain questions are refused before retrieval and before any LLM call.
That is also the cheapest possible path — a refused question costs nothing.

The check is deliberately asymmetric. Refusing a genuine compliance question
is a real harm to a user who needs an answer, while answering a trivia
question is merely embarrassing. So it only refuses when confident: an
explicit off-domain marker, or no domain vocabulary whatsoever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Vocabulary that marks a question as plausibly about standards, certification
# or product compliance. Broad on purpose — a shopkeeper asking "can I sell
# these without approval?" never says "conformity assessment".
IN_DOMAIN = {
    # Bodies and schemes
    "bis", "isi", "crs", "fmcs", "qco", "hallmark", "hallmarking", "huid",
    "manak", "bureau", "ahc", "lrs",
    # Standards. Note "is" is deliberately absent: as a bare word it is the
    # commonest verb in English, and including it for the sake of "IS 17440"
    # made "Who is Virat Kohli?" look like a standards question. IS numbers
    # are matched by IS_NUMBER_REF below, which requires the digits.
    "standard", "standards", "specification", "specifications",
    "iec", "iso", "grade", "grades",
    # Certification and licensing
    "certification", "certificate", "certified", "certify", "licence",
    "license", "licensing", "licensee", "registration", "registered",
    "register", "accreditation", "recognised", "recognition", "scheme",
    "mark", "marking", "marked", "conformity", "compliance", "comply",
    "compliant", "audit", "inspection", "inspect", "surveillance",
    # Regulatory
    "quality", "regulation", "regulations", "regulatory", "mandatory",
    "notified", "notification", "gazette", "order", "amendment", "act",
    "rule", "rules", "provision", "clause", "statutory", "legal", "law",
    "penalty", "penalties", "prosecution", "offence", "cancellation",
    "suspension", "exemption", "exempt", "deadline", "enforcement",
    # Commerce and manufacturing
    "manufacturer", "manufacturing", "manufacture", "factory", "producer",
    "import", "importer", "imported", "export", "exporter", "sell",
    "selling", "sale", "market", "product", "products", "goods", "article",
    "articles", "consignment", "brand", "label", "labelling", "packaging",
    # Testing
    "test", "testing", "tested", "laboratory", "lab", "sample", "sampling",
    "report", "calibration",
    # Consumer
    "consumer", "complaint", "recall", "counterfeit", "fake", "genuine",
    "safety", "jeweller", "jewellery", "gold", "purity", "fineness",
    # Fees and process
    "fee", "fees", "application", "apply", "renewal", "renew", "validity",
    "valid", "procedure", "process", "documents", "checklist",
}

# Subjects that are unmistakably not this assistant's business. Checked as
# whole words so "actor" does not fire on "factory".
OUT_OF_DOMAIN = {
    # People and entertainment
    "cricketer", "cricket", "batsman", "bowler", "footballer", "football",
    "actor", "actress", "filmmaker", "film", "movie", "cinema", "song",
    "singer", "album", "celebrity", "biography", "born", "married",
    # Everyday trivia
    "recipe", "cook", "cooking", "biryani", "weather", "horoscope",
    "joke", "poem", "story", "capital", "population", "tourist",
    # Other government services that share vocabulary with BIS
    "driving", "passport", "aadhaar", "aadhar", "pan card", "voter",
    "ration", "railway", "irctc", "income tax", "gst",
    # Politics and sport
    "election", "minister", "politician", "prime minister", "president",
    "world cup", "olympics", "tournament", "match",
}

# Strong signals that override an out-of-domain word. "Is a driving licence
# accepted as ID proof for BIS registration?" is a legitimate question.
STRONG_IN_DOMAIN = {
    "bis", "isi", "crs", "fmcs", "qco", "hallmark", "hallmarking", "huid",
    "indian standard", "manak", "conformity assessment", "standard mark",
}


# "IS 17440", "IS/IEC 62368" — the digits are what make it a standard
# reference rather than the verb "is".
IS_NUMBER_REF = re.compile(r"\bis\s*(?:/\s*(?:iec|iso|en))?\s*:?\s*\d{2,5}\b", re.IGNORECASE)


# Greetings and pleasantries. These carry no domain vocabulary, so the gate
# would refuse them as off-topic — which reads as rude and makes the
# assistant look broken on the very first thing a person types.
GREETINGS = {
    "hi", "hii", "hiii", "hey", "heya", "hello", "helo", "hlo", "yo",
    "namaste", "namaskar", "namaskaram", "vanakkam", "salaam", "assalamualaikum",
    "hola", "greetings", "gm", "good morning", "good afternoon", "good evening",
    "good day", "morning", "evening",
    "नमस्ते", "नमस्कार", "हाय", "हैलो", "हेलो",
}
# Short courtesies that deserve a human reply rather than a refusal.
COURTESIES = {
    "thanks", "thank you", "thankyou", "thx", "ty", "cheers", "great",
    "ok", "okay", "nice", "perfect", "got it", "bye", "goodbye", "see you",
    "धन्यवाद", "शुक्रिया", "ठीक", "अलविदा",
}
# "who are you", "what can you do" — the assistant should introduce itself.
#
# The Hindi side is matched loosely on purpose. Requiring exact copula
# agreement missed "तुम कौन है?" — grammatically it wants हो, but that is how
# people actually type, and the question fell through to document retrieval
# and came back as "could not answer".
_HI_YOU = r"(?:तुम|आप|तू)"
_HI_BE = r"(?:हो|है|हैं|हूँ|हूं)?"
ABOUT_SELF = re.compile(
    r"^\s*(?:"
    r"who\s+(?:are|r)\s+(?:you|u)|what\s+are\s+you|what\s+(?:can|do)\s+you\s+do|"
    r"how\s+(?:can|do)\s+you\s+help|what\s+is\s+this|who\s+is\s+this|help|"
    r"introduce\s+yourself|about\s+you|your\s+name|"
    rf"{_HI_YOU}\s*कौन\s*{_HI_BE}|"
    rf"{_HI_YOU}\s*क्या\s*(?:कर\s*सकते|करते)\s*{_HI_BE}|"
    r"अपने\s*बारे\s*में\s*बताओ|तुम्हारा\s*नाम\s*क्या\s*है"
    r")\s*[?.!।]*\s*$",
    re.IGNORECASE,
)


class Intent(str):
    GREETING = "greeting"
    COURTESY = "courtesy"
    ABOUT = "about"
    QUESTION = "question"


def classify_intent(question: str) -> str:
    """Small talk versus an actual question.

    Kept separate from the domain gate: a greeting is neither in-domain nor
    off-domain, and answering it warmly costs nothing while refusing it makes
    the assistant feel hostile on first contact.
    """
    q = (question or "").strip().lower().rstrip("!?.,")
    q = re.sub(r"\s+", " ", q)
    if not q:
        return Intent.QUESTION
    if q in GREETINGS or (len(q.split()) <= 3 and q.split()[0] in GREETINGS):
        return Intent.GREETING
    if q in COURTESIES:
        return Intent.COURTESY
    if ABOUT_SELF.match(q):
        return Intent.ABOUT
    return Intent.QUESTION


@dataclass
class ScopeVerdict:
    in_scope: bool
    reason: str


def _words(text: str) -> set[str]:
    """Words, plus a crude singular for each.

    Matching on exact forms alone rejected "imports", "licences" and
    "documents" while accepting their singulars — a false refusal of a real
    compliance question, which is the costly direction to get wrong.
    """
    found = set(re.findall(r"[a-z]+", text.lower()))
    for w in list(found):
        if len(w) > 3:
            if w.endswith("ies"):
                found.add(w[:-3] + "y")
            elif w.endswith("es"):
                found.add(w[:-2])
            if w.endswith("s"):
                found.add(w[:-1])
    return found


def check_scope(question: str) -> ScopeVerdict:
    """Decide whether to engage with this question at all."""
    q = (question or "").strip()
    if len(q) < 3:
        return ScopeVerdict(False, "empty question")

    lowered = q.lower()
    words = _words(lowered)

    # A strong BIS signal settles it, whatever else the sentence contains.
    if any(term in lowered for term in STRONG_IN_DOMAIN) or IS_NUMBER_REF.search(lowered):
        return ScopeVerdict(True, "explicit BIS/standards reference")

    # Devanagari questions are given the benefit of the doubt: the lexicon is
    # English, so absence of matches proves nothing about a Hindi question.
    if re.search(r"[ऀ-ॿ]", q):
        return ScopeVerdict(True, "hindi question — english lexicon cannot judge it")

    hits_out = {w for w in words if w in OUT_OF_DOMAIN}
    hits_out |= {p for p in OUT_OF_DOMAIN if " " in p and p in lowered}
    if hits_out:
        return ScopeVerdict(False, f"off-domain subject: {', '.join(sorted(hits_out))}")

    if not (words & IN_DOMAIN):
        return ScopeVerdict(False, "no standards, certification or product-compliance terms")

    return ScopeVerdict(True, "domain vocabulary present")


REFUSAL_EN = (
    "That question is outside what I handle. I answer only questions about "
    "Indian Standards, BIS certification, licensing, hallmarking, Quality "
    "Control Orders and related product-compliance matters, so I will not "
    "answer this one.\n\n"
    "Ask me something like which standard applies to a product, how to get a "
    "BIS licence, what a hallmark means, or which scheme covers your goods."
)

REFUSAL_HI = (
    "यह प्रश्न मेरे कार्यक्षेत्र से बाहर है। मैं केवल भारतीय मानकों, बीआईएस प्रमाणन, "
    "लाइसेंस, हॉलमार्किंग, गुणवत्ता नियंत्रण आदेश और उत्पाद अनुपालन से जुड़े प्रश्नों का "
    "उत्तर देता हूँ, इसलिए मैं इसका उत्तर नहीं दूँगा।\n\n"
    "आप पूछ सकते हैं कि किसी उत्पाद पर कौन सा मानक लागू होता है, बीआईएस लाइसेंस कैसे "
    "प्राप्त करें, हॉलमार्क का क्या अर्थ है, या आपके सामान पर कौन सी योजना लागू होती है।"
)


def refusal_text(language: str | None) -> str:
    return REFUSAL_HI if (language or "").startswith("Hindi") else REFUSAL_EN


SMALL_TALK = {
    Intent.GREETING: {
        "en": (
            "Hello. I am Manak Sahayak, an assistant for Indian Standards and BIS "
            "matters.\n\n"
            "You can ask me which standard applies to a product, how to get a BIS "
            "licence, what a hallmark or ISI mark means, which Quality Control Order "
            "covers your goods, or how a foreign manufacturer gets certified. "
            "Ask in English or हिन्दी."
        ),
        "hi": (
            "नमस्ते। मैं मानक सहायक हूँ — भारतीय मानकों और बीआईएस से जुड़े प्रश्नों का सहायक।\n\n"
            "आप पूछ सकते हैं कि किसी उत्पाद पर कौन सा मानक लागू होता है, बीआईएस लाइसेंस कैसे "
            "प्राप्त करें, हॉलमार्क या आईएसआई चिह्न का क्या अर्थ है, आपके सामान पर कौन सा "
            "गुणवत्ता नियंत्रण आदेश लागू होता है, या विदेशी विनिर्माता प्रमाणन कैसे लेते हैं।"
        ),
    },
    Intent.COURTESY: {
        "en": "Happy to help. Ask me anything else about Indian Standards, BIS "
              "certification, hallmarking or Quality Control Orders.",
        "hi": "सहायता करके खुशी हुई। भारतीय मानकों, बीआईएस प्रमाणन, हॉलमार्किंग या गुणवत्ता "
              "नियंत्रण आदेशों के बारे में कुछ और पूछें।",
    },
    Intent.ABOUT: {
        "en": (
            "I am Manak Sahayak, an assistant for Indian Standards and Bureau of "
            "Indian Standards (BIS) matters.\n\n"
            "I answer from a corpus of official BIS documents indexed on this "
            "machine, and every fact I state carries a reference to the document and "
            "page it came from. Where the documents do not cover something, I say so "
            "and mark any general guidance clearly as unverified.\n\n"
            "I can help with: which Indian Standard applies to a product, BIS "
            "certification schemes (ISI, CRS, FMCS), hallmarking and HUID, Quality "
            "Control Orders and their amendments, licences, fees and penalties. "
            "I do not answer questions outside these subjects."
        ),
        "hi": (
            "मैं मानक सहायक हूँ — भारतीय मानक और भारतीय मानक ब्यूरो (बीआईएस) से जुड़े "
            "विषयों का सहायक।\n\n"
            "मैं इस मशीन पर अनुक्रमित आधिकारिक बीआईएस दस्तावेज़ों से उत्तर देता हूँ, और हर तथ्य "
            "के साथ उस दस्तावेज़ और पृष्ठ का संदर्भ रहता है। जहाँ दस्तावेज़ों में जानकारी नहीं होती, "
            "वहाँ मैं स्पष्ट रूप से बता देता हूँ।\n\n"
            "मैं इनमें सहायता कर सकता हूँ: किसी उत्पाद पर लागू भारतीय मानक, बीआईएस प्रमाणन "
            "योजनाएँ (ISI, CRS, FMCS), हॉलमार्किंग और HUID, गुणवत्ता नियंत्रण आदेश और उनके "
            "संशोधन, लाइसेंस, शुल्क और दंड। इनसे बाहर के प्रश्नों का उत्तर मैं नहीं देता।"
        ),
    },
}


def small_talk_text(intent: str, language: str | None) -> str | None:
    entry = SMALL_TALK.get(intent)
    if not entry:
        return None
    return entry["hi"] if (language or "").startswith("Hindi") else entry["en"]
