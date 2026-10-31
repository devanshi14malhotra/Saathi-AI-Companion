import re
from typing import Any

from app.core.config import cfg_mgr
from app.llm.provider import get_provider, get_provider_name

ID_EXTRACT_RE = re.compile(r"\b[A-Z]{1,4}-\d+[a-z]?\b")
DATE_EXTRACT_RE = re.compile(r"\b\d{1,2}\s+[A-Z][a-z]{2}\b")
NUM_EXTRACT_RE = re.compile(r"\d[\d,]*")

TONE_MAP = {
    "calm": "neutral",
    "frustrated": "empathetic",
    "angry": "apologetic and calm",
    "panicked": "reassuring",
}


def get_template_text(code: str, language: str) -> str:
    lang = language if language in ("en", "hinglish", "hi") else "en"
    entry = cfg_mgr.templates.get(code, {})
    if isinstance(entry, dict):
        return entry.get(lang) or entry.get("en") or ""
    return str(entry)


def post_check_rewrite(output: str, static_rendered: str, facts: dict[str, Any]) -> bool:
    """
    SPEC §8.9 step 3:
    Extract IDs ([A-Z]{1,4}-\\d+[a-z]?), dates (\\d{1,2} [A-Z][a-z]{2}), and numbers (\\d[\\d,]*, after removing IDs and dates).
    Every extracted token must appear in the facts' rendered values, and every numeric fact the template contains must appear in the output.
    """
    if not output or not output.strip():
        return False

    fact_str_values = " ".join(str(v) for v in facts.values() if v is not None)
    fact_str_no_commas = fact_str_values.replace(",", "")

    # Extract IDs and dates from output
    out_ids = ID_EXTRACT_RE.findall(output)
    for token_id in out_ids:
        if token_id not in fact_str_values and token_id not in static_rendered:
            return False

    out_dates = DATE_EXTRACT_RE.findall(output)
    for d in out_dates:
        if d not in fact_str_values and d not in static_rendered:
            return False

    # Strip IDs and dates before extracting numbers
    out_scrubbed = ID_EXTRACT_RE.sub(" ", output)
    out_scrubbed = DATE_EXTRACT_RE.sub(" ", out_scrubbed)
    out_nums = [n.replace(",", "") for n in NUM_EXTRACT_RE.findall(out_scrubbed)]

    static_scrubbed = ID_EXTRACT_RE.sub(" ", static_rendered)
    static_scrubbed = DATE_EXTRACT_RE.sub(" ", static_scrubbed)
    expected_nums = [n.replace(",", "") for n in NUM_EXTRACT_RE.findall(static_scrubbed)]

    allowed_nums = set(expected_nums)
    for v in facts.values():
        if isinstance(v, (int, float)):
            allowed_nums.add(str(int(v)))

    for n in out_nums:
        if n not in allowed_nums and n not in fact_str_no_commas:
            return False

    for exp_n in expected_nums:
        if exp_n not in out_nums:
            return False

    # Check IDs from static_rendered are preserved in output
    expected_ids = ID_EXTRACT_RE.findall(static_rendered)
    for eid in expected_ids:
        if eid not in out_ids:
            return False

    return True


async def compose_message(
    template_code: str,
    facts: dict[str, Any],
    language: str,
    sentiment: str = "calm",
    case_id: str | None = None,
    provider_override: Any = None,
) -> tuple[str, bool]:
    """
    Returns (final_text, used_fallback: bool).
    """
    lang = language if language in ("en", "hinglish", "hi") else "en"
    raw_template = get_template_text(template_code, lang)
    safe_facts = {k: ("" if v is None else v) for k, v in facts.items()}
    try:
        static_rendered = raw_template.format(**safe_facts)
    except KeyError:
        static_rendered = raw_template
        for k, v in safe_facts.items():
            static_rendered = static_rendered.replace(f"{{{k}}}", str(v))

    rewrite_enabled = bool(cfg_mgr.llm.get("rewrite_enabled", True))
    provider_name = get_provider_name()
    provider = provider_override or get_provider()

    if rewrite_enabled and (provider_override is not None or provider_name != "stub"):
        tone = TONE_MAP.get(sentiment, "neutral")
        try:
            rewritten = await provider.rewrite(raw_template, safe_facts, lang, tone, case_id=case_id)
            if post_check_rewrite(rewritten, static_rendered, safe_facts):
                return rewritten, False
            return static_rendered, True
        except Exception:
            return static_rendered, True

    return static_rendered, False


def build_resolution_sections(diagnosis: str, facts: dict[str, Any]) -> dict[str, str]:
    """
    SPEC §9: Build What we found / What we did / What happens next in code from diagnosis and verified facts.
    """
    amount = facts.get("amount")
    txn_id = facts.get("txn_id", "")
    refund_id = facts.get("refund_id", "")
    counterparty = facts.get("counterparty", "merchant")
    sla_hours = facts.get("sla_hours", 72)
    eta = facts.get("eta", "")
    recon_id = facts.get("recon_id", "")
    ticket_id = facts.get("ticket_id", "")
    next_date = facts.get("next_date", "")

    if diagnosis == "REFUND_DUE":
        return {
            "found": f"₹{amount} was debited for {txn_id} ({counterparty}) but the payment failed.",
            "did": f"Started refund {refund_id} for ₹{amount}.",
            "next": f"Expected in your account within {sla_hours} hours (by {eta}).",
        }
    if diagnosis == "DUPLICATE_DEBIT":
        return {
            "found": f"Two charges of ₹{amount} at {counterparty}; extra debit {txn_id} failed to credit.",
            "did": f"Started refund {refund_id} for the extra ₹{amount} debit.",
            "next": f"Expected in your account within {sla_hours} hours (by {eta}).",
        }
    if diagnosis == "TXN_SUCCEEDED":
        return {
            "found": f"Transaction {txn_id} for ₹{amount} to {counterparty} succeeded and merchant was credited.",
            "did": "No action needed.",
            "next": "Your payment is complete with the merchant.",
        }
    if diagnosis == "NO_DEBIT":
        return {
            "found": f"Transaction {txn_id} for ₹{amount} to {counterparty} failed with no bank debit.",
            "did": "No action needed.",
            "next": "You can safely retry the payment.",
        }
    if diagnosis == "REVERSAL_PENDING":
        return {
            "found": f"₹{amount} for {txn_id} ({counterparty}) is pending with bank auto-reversal scheduled.",
            "did": f"Scheduled automatic follow-up check for {eta}.",
            "next": f"Bank auto-reversal expected within {sla_hours} hours (by {eta}).",
        }
    if diagnosis == "REFUND_ETA":
        return {
            "found": f"Refund {refund_id} of ₹{amount} for {txn_id} is currently processing.",
            "did": "Verified active refund status with banking rail.",
            "next": f"Expected in your account by {eta}.",
        }
    if diagnosis == "RECON_RAISED":
        return {
            "found": f"Refund/settlement {refund_id or txn_id} of ₹{amount} crossed the standard SLA window.",
            "did": f"Raised bank reconciliation {recon_id}.",
            "next": "Banking ops will update your case once reconciliation clears.",
        }
    if diagnosis == "SETTLEMENT_HOLIDAY":
        return {
            "found": f"Settlement {refund_id} of ₹{amount} was paused due to a bank holiday.",
            "did": "Verified settlement schedule against bank holiday calendar.",
            "next": f"Scheduled to credit on the next working day ({next_date}).",
        }
    if diagnosis == "SETTLEMENT_MISMATCH":
        return {
            "found": f"Settlement {refund_id} credited ₹{facts.get('actual')} vs expected ₹{facts.get('expected')}.",
            "did": f"Raised reconciliation {recon_id} for ₹{facts.get('diff')}.",
            "next": "Difference will be credited after reconciliation review.",
        }
    if diagnosis == "BUG_FILED":
        return {
            "found": "App crash reported; device diagnostics captured.",
            "did": f"Created engineering ticket {ticket_id}.",
            "next": "Follow the troubleshooting steps above while engineering investigates.",
        }
    if diagnosis in ("APP_GUIDE", "LOGIN_OTP_HELP"):
        return {
            "found": "Matched your question to verified help documentation.",
            "did": "Provided step-by-step troubleshooting instructions.",
            "next": "Let us know if you still need assistance.",
        }
    return {
        "found": f"Reviewed case {facts.get('case_id', '')}.",
        "did": "Verified account records.",
        "next": "See message details above.",
    }

