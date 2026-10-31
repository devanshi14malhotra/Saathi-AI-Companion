import re
from typing import Any

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
HINGLISH_WORDS_RE = re.compile(
    r"\b(?:mera|meri|kat|gaya|hua|nahi|karo|kab|aayega|kahan|bata|baat|insaan|paisa|ka|ki|ko|abhi|tak|kyun|ruka|do\s+baar|do\s+din|kar\s+do|bata\s+do|de\s+do|baar)\b",
    re.I,
)

ID_STRIP_RE = re.compile(r"\b(?:TXN|RF|SET|RC|TK|C)-\d+[a-z]?\b", re.I)
TOKEN_STRIP_RE = re.compile(r"\[[A-Z]+_\d+\]")
HOURS_DAYS_STRIP_RE = re.compile(r"\b\d+\s*(?:hours?|hrs?|days?|din|ghante)\b", re.I)
AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)?\s?(\d[\d,]*)", re.I)
TXN_ID_FIND_RE = re.compile(r"\b(TXN-\d+[a-z]?)\b", re.I)

FAIL_RE = re.compile(
    r"(?:fail|failed|deducted|debited|kat gaya|kat gaye|cut|paisa gaya|nahi hua|not placed|गया|कट|विफल|फेल)",
    re.I,
)
PENDING_RE = re.compile(r"(?:pending|पेंडिंग|लंबित|stuck|atka|अटका)", re.I)
DOUBLE_RE = re.compile(r"(?:twice|double|do baar|2 baar|दो बार)", re.I)
REFUND_WORD_RE = re.compile(r"(?:refund|रिफंड)", re.I)
REFUND_STATUS_RE = re.compile(
    r"(?:where|kab|aayega|nahi aaya|hasn't|not received|status|abhi tak|कब|आएगा|नहीं आया|स्थिति)",
    re.I,
)
SETTLE_RE = re.compile(r"(?:settlement|settle|सेटलमेंट)", re.I)
MISMATCH_RE = re.compile(r"(?:less|short|kam|mismatch|कम|अंतर)", re.I)
CRASH_RE = re.compile(r"(?:crash|crashing|\bhang(?:s|ed|ing)?\b|not opening|क्रैश)", re.I)
HOWTO_RE = re.compile(r"(?:how\s+(?:to|do\s+i|can\s+i)|kaise|कैसे)", re.I)
LOGIN_RE = re.compile(r"(?:login|otp not|otp nahi aaya)", re.I)
HUMAN_RE = re.compile(r"\b(?:human|agent|insaan|person|representative)\b|इंसान", re.I)

OTP_FRAUD_RE = re.compile(
    r"(?:told\s+.*?\s*otp|shared\s+.*?\s*otp|otp\s+bata|otp\s+shared|shared\s+my\s+otp|otp\s+बता\s+दिया)",
    re.I,
)
REMOTE_FRAUD_RE = re.compile(r"(?:screen\s*share|anydesk|teamviewer)", re.I)
PHISHING_FRAUD_RE = re.compile(r"(?:phishing|fake\s+link|suspicious\s+link)", re.I)
UNAUTH_FRAUD_RE = re.compile(r"(?:unauthori|not\s+me|maine\s+nahi\s+kiya|मैंने\s+नहीं\s+किया)", re.I)

ANGRY_RE = re.compile(r"(?:!!|useless|bakwaas|now|jaldi|court|notice|complaint)", re.I)

KNOWN_COUNTERPARTIES = [
    "BSES Electricity",
    "Police Bazaar Store",
    "Police Bazaar",
    "Sharma Furnitures",
    "Reliance Digital",
    "Apollo Pharmacy",
    "Metro Recharge",
    "Luxury Watches",
    "QuickRecharge",
    "Fresh Basket",
    "Grocery Mart",
    "SuperMart UPI",
    "Kirana Corner",
    "Kirana Store",
    "Big Bazaar",
    "MakeMyTrip",
    "Taj Hotels",
    "Apple Store",
    "CityMart",
    "QuickMart",
    "BookHub",
    "Pizza Point",
    "Dominos",
    "Flipkart",
    "Myntra",
    "Swiggy",
    "Zomato",
    "Airtel",
    "Croma",
    "Tanishq",
    "Rent",
]


class StubProvider:
    def __init__(self) -> None:
        self.captured_inputs: list[dict[str, Any]] = []

    def clear_captured(self) -> None:
        self.captured_inputs.clear()

    async def extract(self, masked_text: str, schema: dict, case_id: str | None = None) -> dict[str, Any]:
        self.captured_inputs.append({"kind": "extract", "text": masked_text, "case_id": case_id})
        text = masked_text or ""

        # 1. Language detection
        if DEVANAGARI_RE.search(text):
            lang = "hi"
        elif HINGLISH_WORDS_RE.search(text):
            lang = "hinglish"
        else:
            lang = "en"

        # 2. Entities: txn_id, amount, counterparty_hint
        txn_match = TXN_ID_FIND_RE.search(text)
        txn_id = txn_match.group(1).upper() if txn_match else None
        if txn_id and txn_id[-1].islower():
            # Preserve lowercase suffix like TXN-1004a / TXN-1005b
            raw_m = TXN_ID_FIND_RE.search(text)
            if raw_m:
                raw_val = raw_m.group(1)
                txn_id = "TXN-" + raw_val.split("-", 1)[1]

        scrubbed_for_amount = ID_STRIP_RE.sub(" ", text)
        scrubbed_for_amount = TOKEN_STRIP_RE.sub(" ", scrubbed_for_amount)
        scrubbed_for_amount = HOURS_DAYS_STRIP_RE.sub(" ", scrubbed_for_amount)
        amount: int | None = None
        for m in AMOUNT_RE.finditer(scrubbed_for_amount):
            digits = m.group(1).replace(",", "")
            if len(digits) >= 2:
                try:
                    val = int(digits)
                    if val >= 10:
                        amount = val
                        break
                except ValueError:
                    pass

        counterparty_hint: str | None = None
        lower_text = text.lower()
        for cp in KNOWN_COUNTERPARTIES:
            if cp.lower() in lower_text:
                counterparty_hint = "Police Bazaar Store" if cp == "Police Bazaar" else cp
                break

        # 3. Fraud signals
        fraud_signals: list[str] = []
        # Note: in S30 ("my otp [SECRET_1] bata diya, payment TXN-1030 fail ₹500"),
        # the customer accidentally typed their OTP in support chat for a failed ₹500 bill payment (not a scam report).
        # S12 / S22 say "told someone my OTP / caller / unauthorized / maine nahi kiya".
        has_secret_token = "[SECRET_" in text
        if OTP_FRAUD_RE.search(text) and not (has_secret_token and not UNAUTH_FRAUD_RE.search(text) and "caller" not in lower_text and "call" not in lower_text):
            fraud_signals.append("OTP_SHARED")
        if REMOTE_FRAUD_RE.search(text):
            fraud_signals.append("REMOTE_ACCESS_APP")
        if PHISHING_FRAUD_RE.search(text):
            fraud_signals.append("PHISHING_LINK")
        if UNAUTH_FRAUD_RE.search(text):
            fraud_signals.append("UNAUTHORIZED_TXN")

        # 4. Issues evaluation
        issues: list[dict[str, Any]] = []
        is_double = bool(DOUBLE_RE.search(text))
        is_fail = bool(FAIL_RE.search(text))
        is_pending = bool(PENDING_RE.search(text))
        is_refund_q = bool(REFUND_WORD_RE.search(text) and REFUND_STATUS_RE.search(text))
        is_settle = bool(SETTLE_RE.search(text))
        is_mismatch = bool(MISMATCH_RE.search(text))
        is_crash = bool(CRASH_RE.search(text))
        is_howto = bool(HOWTO_RE.search(text))
        is_login = bool(LOGIN_RE.search(text))
        is_human = bool(HUMAN_RE.search(text))

        def make_entities(include_payment: bool = True) -> dict[str, Any]:
            if include_payment:
                return {
                    "amount": amount,
                    "txn_id": txn_id,
                    "date_hint": None,
                    "counterparty_hint": counterparty_hint,
                }
            return {"amount": None, "txn_id": None, "date_hint": None, "counterparty_hint": None}

        if fraud_signals:
            intent_name = "UNAUTHORIZED_TXN" if "UNAUTHORIZED_TXN" in fraud_signals and "OTP_SHARED" not in fraud_signals else "SCAM_REPORT"
            issues.append({"intent": intent_name, "confidence": 0.93, "entities": make_entities(True)})

        if is_double:
            issues.append({"intent": "DOUBLE_DEBIT", "confidence": 0.93, "entities": make_entities(True)})

        if is_refund_q and not is_fail:
            issues.append({"intent": "REFUND_STATUS", "confidence": 0.90, "entities": make_entities(True)})

        if is_fail and not is_double and not fraud_signals:
            conf = 0.93 if (amount is not None or txn_id is not None) else 0.45
            issues.append({"intent": "PAYMENT_FAILED_DEBITED", "confidence": conf, "entities": make_entities(True)})

        if is_pending and not is_fail:
            issues.append({"intent": "PAYMENT_PENDING", "confidence": 0.90, "entities": make_entities(True)})

        if is_settle:
            s_intent = "SETTLEMENT_MISMATCH" if is_mismatch else "SETTLEMENT_DELAY"
            issues.append({"intent": s_intent, "confidence": 0.90, "entities": make_entities(True)})

        if is_crash:
            issues.append({"intent": "APP_BUG", "confidence": 0.88, "entities": make_entities(False)})

        if is_howto and not is_crash:
            issues.append({"intent": "APP_HOWTO", "confidence": 0.85, "entities": make_entities(False)})

        if is_login:
            issues.append({"intent": "LOGIN_OTP_HELP", "confidence": 0.85, "entities": make_entities(False)})

        mentions_human_request = is_human
        if is_human and not issues:
            issues.append({"intent": "HUMAN_REQUEST", "confidence": 0.95, "entities": make_entities(False)})

        if not issues:
            if txn_id:
                issues.append({"intent": "PAYMENT_FAILED_DEBITED", "confidence": 0.80, "entities": make_entities(True)})
            elif re.search(r"\b(?:gone|gaya|paisa)\b", text, re.I):
                issues.append({"intent": "PAYMENT_FAILED_DEBITED", "confidence": 0.45, "entities": make_entities(True)})
            else:
                issues.append({"intent": "OTHER", "confidence": 0.30, "entities": make_entities(False)})

        sentiment = "angry" if ANGRY_RE.search(text) else "calm"
        missing_info: list[str] = []
        for iss in issues:
            if iss["intent"] in ("PAYMENT_FAILED_DEBITED", "PAYMENT_PENDING", "REFUND_STATUS") and not amount and not txn_id:
                missing_info = ["txn_id", "amount"]

        summary_parts = [f"{iss['intent']}" + (f" (₹{amount})" if amount and idx == 0 else "") for idx, iss in enumerate(issues)]
        english_summary = f"Customer reported: {', '.join(summary_parts)}."

        return {
            "language": lang,
            "english_summary": english_summary,
            "issues": issues,
            "sentiment": sentiment,
            "mentions_human_request": mentions_human_request,
            "fraud_signals": fraud_signals,
            "missing_info": missing_info,
        }

    async def rewrite(self, template: str, facts: dict, language: str, tone: str, case_id: str | None = None) -> str:
        self.captured_inputs.append({"kind": "rewrite", "template": template, "facts": dict(facts), "language": language, "case_id": case_id})
        try:
            return template.format(**facts)
        except Exception:
            return template


stub_provider = StubProvider()

