import re
from typing import Literal

from pydantic import BaseModel, Field

IntentLiteral = Literal[
    "PAYMENT_FAILED_DEBITED",
    "PAYMENT_PENDING",
    "DOUBLE_DEBIT",
    "REFUND_STATUS",
    "REFUND_NOT_RECEIVED",
    "SETTLEMENT_DELAY",
    "SETTLEMENT_MISMATCH",
    "APP_HOWTO",
    "APP_BUG",
    "LOGIN_OTP_HELP",
    "UNAUTHORIZED_TXN",
    "SCAM_REPORT",
    "HUMAN_REQUEST",
    "OTHER",
]

FraudSignalLiteral = Literal[
    "OTP_SHARED",
    "REMOTE_ACCESS_APP",
    "PHISHING_LINK",
    "UNAUTHORIZED_TXN",
    "UNKNOWN_DEVICE",
]


class Entities(BaseModel):
    amount: int | None = None
    txn_id: str | None = None
    date_hint: str | None = None
    counterparty_hint: str | None = None


class Issue(BaseModel):
    intent: IntentLiteral
    confidence: float = Field(ge=0.0, le=1.0)
    entities: Entities = Field(default_factory=Entities)


class Extraction(BaseModel):
    language: Literal["en", "hi", "hinglish", "other"] = "en"
    english_summary: str = ""
    issues: list[Issue]
    sentiment: Literal["calm", "frustrated", "angry", "panicked"] = "calm"
    mentions_human_request: bool = False
    fraud_signals: list[FraudSignalLiteral] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


TXN_ID_RE = re.compile(r"^TXN-\d+[a-z]?$")


def post_process_extraction(ext: Extraction) -> Extraction:
    for issue in ext.issues:
        if issue.entities.txn_id and not TXN_ID_RE.match(issue.entities.txn_id):
            issue.entities.txn_id = None
    if not ext.issues:
        ext.issues = [Issue(intent="OTHER", confidence=0.0)]
    return ext


def fallback_extraction() -> Extraction:
    return Extraction(
        language="en",
        english_summary="Unable to extract structured issue; routed to fallback.",
        issues=[Issue(intent="OTHER", confidence=0.0)],
        sentiment="calm",
        mentions_human_request=False,
        fraud_signals=[],
        missing_info=[],
    )

