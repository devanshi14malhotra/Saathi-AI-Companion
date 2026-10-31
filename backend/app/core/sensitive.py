from dataclasses import dataclass, field
from app.core.config import cfg_mgr


@dataclass
class SensitiveMatch:
    matched: bool = False
    is_distress: bool = False
    categories: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)


def detect_sensitive(clean_masked_text: str) -> SensitiveMatch:
    """
    Deterministic phrase-level detection over masked, guard-cleaned text (SPEC_V6 §5.1).
    Does NOT match bare 'police', 'fir', 'lawyer' inside merchant names like 'Police Bazaar'.
    """
    if not clean_masked_text:
        return SensitiveMatch()

    lower = clean_masked_text.lower()
    categories_cfg = cfg_mgr.sensitive or {}
    matched_cats: list[str] = []
    matched_phrases: list[str] = []
    is_distress = False

    for cat, phrases in categories_cfg.items():
        if not isinstance(phrases, list):
            continue
        for phrase in phrases:
            p_low = str(phrase).strip().lower()
            if p_low and p_low in lower:
                if cat not in matched_cats:
                    matched_cats.append(cat)
                matched_phrases.append(str(phrase))
                if cat == "distress":
                    is_distress = True

    return SensitiveMatch(
        matched=bool(matched_phrases),
        is_distress=is_distress,
        categories=matched_cats,
        phrases=matched_phrases,
    )

