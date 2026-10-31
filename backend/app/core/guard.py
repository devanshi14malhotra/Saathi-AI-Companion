import re

GUARD = [
    re.compile(p, re.I)
    for p in [
        r"ignore\s+(?:all\s+|your\s+|previous\s+|the\s+)?(?:rules|instructions)",
        r"(?:rules|instructions)\s+(?:ko\s+)?ignore",
        r"you are now|\bact as\b|pretend to be",
        r"(?:system|developer)\s+prompt",
        r"refund\s+(?:me\s+)?(?:₹|rs\.?|inr)?\s?\d[\d,]*\s*(?:now|immediately|right now)",
        r"\d[\d,]*\s*(?:ka\s+)?refund\s+(?:karo|do)\b",
        r"(?:approve|override|bypass)\s+(?:the\s+)?(?:policy|limit|cap|approval)",
        r"\bas\s+(?:an\s+)?admin\b",
    ]
]
SPLIT = re.compile(r"(?<=[.!?।»])\s+(?=[^\d₹])")

HOMOGLYPH_MAP = str.maketrans(
    {
        "\u0456": "i",  # Cyrillic small i
        "\u0406": "I",  # Cyrillic capital I
        "\u0430": "a",  # Cyrillic small a
        "\u0435": "e",  # Cyrillic small e
        "\u043e": "o",  # Cyrillic small o
        "\u0440": "p",  # Cyrillic small er
        "\u0441": "c",  # Cyrillic small es
        "\u0445": "x",  # Cyrillic small ha
        "\u200b": "",   # zero-width space
        "\u200c": "",
        "\u200d": "",
    }
)

SPACED_WORD_RE = re.compile(r"\b(?:[a-zA-Z]\s+){3,}[a-zA-Z]\b")


def _normalize_for_guard(s: str) -> str:
    norm = s.translate(HOMOGLYPH_MAP)
    norm = SPACED_WORD_RE.sub(lambda m: m.group(0).replace(" ", ""), norm)
    return norm


def scan(text: str) -> tuple[str, bool, list[str]]:
    """Returns (clean_text, hit: bool, removed: list[str])."""
    if not text or not text.strip():
        return "", False, []
    sentences = SPLIT.split(text.strip())
    kept: list[str] = []
    removed: list[str] = []
    for s in sentences:
        norm_s = _normalize_for_guard(s)
        if any(p.search(s) or p.search(norm_s) for p in GUARD):
            removed.append(s)
        else:
            cleaned_clause = s.replace("Please translate and execute:", "").replace("«", "").replace("»", "").strip()
            if cleaned_clause:
                kept.append(cleaned_clause)
    return " ".join(kept).strip(), bool(removed), removed
