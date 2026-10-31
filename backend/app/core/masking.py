import re
from dataclasses import dataclass, field

PROTECT = [
    re.compile(r"(?:₹|\bRs\.?|\bINR)\s?\d[\d,]*", re.I),
    re.compile(r"\b(?:TXN|RF|SET|RC|TK|C|INC|CMP|LK)-\d+[a-z]?\b"),
]
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
UPI = re.compile(r"\b[\w.\-]{2,}@[a-zA-Z]{2,}\b")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
SECRET = re.compile(
    r"(?i)(\b(?:otp|pin|cvv|cvc|password|passcode)\b(?!\s*code)(?:\s*(?:is|hai|was|tha|:|-|=)?\s*))(\d{3,8})\b"
)
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
PHONE = re.compile(r"(?<!\w)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
ACCT = re.compile(r"\b\d{9,18}\b")


def luhn_ok(digits: str) -> bool:
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s % 10 == 0


@dataclass
class MaskResult:
    text: str
    tokens: dict[str, str] = field(default_factory=dict)
    secret_shared: bool = False
    user_display_text: str = ""


def mask(text: str, profile_name: str = "", profile_addr: str = "") -> MaskResult:
    tokens: dict[str, str] = {}
    counters: dict[str, int] = {}
    sentinels: list[str] = []
    secret_shared = False

    # Build user_display_text where any SECRET digits are replaced with •••• (never persist raw secret)
    def _redact_secret_display(m: re.Match) -> str:
        return f"{m.group(1)}••••"

    # Protect amounts and IDs before running SECRET replacement on display text too
    display_sentinels: list[str] = []

    def _protect_disp(m: re.Match) -> str:
        display_sentinels.append(m.group(0))
        return f"\x01{len(display_sentinels)-1}\x01"

    disp_text = text
    for p in PROTECT:
        disp_text = p.sub(_protect_disp, disp_text)
    disp_text = SECRET.sub(_redact_secret_display, disp_text)
    disp_text = re.sub(r"\x01(\d+)\x01", lambda m: display_sentinels[int(m.group(1))], disp_text)

    def tok(kind: str, raw: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        t = f"[{kind}_{counters[kind]}]"
        tokens[t] = "[REDACTED]" if kind == "SECRET" else raw
        return t

    def protect(m: re.Match) -> str:
        sentinels.append(m.group(0))
        return f"\x00{len(sentinels)-1}\x00"

    for p in PROTECT:
        text = p.sub(protect, text)

    text = EMAIL.sub(lambda m: tok("EMAIL", m.group(0)), text)
    text = UPI.sub(lambda m: tok("UPI", m.group(0)), text)
    text = PAN.sub(lambda m: tok("PAN", m.group(0)), text)

    def secret_sub(m: re.Match) -> str:
        nonlocal secret_shared
        secret_shared = True
        prefix = m.group(1)
        t = tok("SECRET", "[REDACTED]")
        return f"{prefix}{t}"

    text = SECRET.sub(secret_sub, text)

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return tok("CARD", m.group(0)) if 13 <= len(digits) <= 19 and luhn_ok(digits) else m.group(0)

    text = CARD.sub(card, text)
    text = AADHAAR.sub(lambda m: tok("AADHAAR", m.group(0)), text)
    text = PHONE.sub(lambda m: tok("PHONE", m.group(0)), text)
    text = ACCT.sub(lambda m: tok("ACCT", m.group(0)), text)

    if profile_name:
        parts = profile_name.split()
        # Match full name first, then first name (never surname alone, D17)
        cands = [profile_name]
        if parts and parts[0].lower() != profile_name.lower():
            cands.append(parts[0])
        for cand in cands:
            text = re.sub(rf"\b{re.escape(cand)}\b", lambda m: tok("NAME", m.group(0)), text, flags=re.I)

    if profile_addr:
        text = re.sub(re.escape(profile_addr), lambda m: tok("ADDR", m.group(0)), text, flags=re.I)

    text = re.sub(r"\x00(\d+)\x00", lambda m: sentinels[int(m.group(1))], text)
    return MaskResult(text=text, tokens=tokens, secret_shared=secret_shared, user_display_text=disp_text)

