from typing import Any

from app.core.composer import get_template_text

RECOMMENDED_ACTION_BY_TRIGGER = {
    "T1": "Contact customer, review lock, verify with bank",
    "T2": "Take over and reply",
    "T3": "Reconcile ledger vs bank record manually",
    "T4": "Review the hold; contact the customer with an ETA",
    "T5": "Review and approve manually (amount above ceiling)",
    "T6": "Retry once the system is back; check for a duplicate first",
    "T7": "Contact the customer to identify the transaction",
    "T8": "Contact the customer with priority and empathy. Do not argue. Follow the sensitive-case playbook.",
    "KS": "Review paused agent queue; resume agent when ready or handle manually.",
}


def build_why_you_line(
    rule: str,
    agent_name: str,
    amount: int | None,
    cap: int | None,
    confidence_score: float | None,
    min_conf: float = 0.70,
) -> str:
    """SPEC_V6 §6 F6 item 2: Why you? one line from a fixed map."""
    if rule == "4":
        return f"Refund ₹{amount or 0:,} exceeds {agent_name} auto limit ₹{cap or 0:,}"
    if rule == "3c":
        return f"Confidence {(confidence_score or 0.0):.2f} is below the auto threshold {min_conf:.2f}"
    if rule == "3v":
        return "Velocity limit reached for this customer"
    if rule == "T1":
        return "Fraud signal present"
    if rule == "T2":
        return "Customer asked for a person"
    if rule == "T3":
        return "Systems disagree after a re-check"
    if rule == "T4":
        return "Risk or compliance hold"
    if rule == "T5":
        return "Amount above ceiling"
    if rule == "T6":
        return "A system failed after retries"
    if rule == "T7":
        return "Couldn't identify the transaction"
    if rule == "T8":
        return "Sensitive or vulnerable customer"
    if rule == "KS":
        return "Agent paused by a team lead"
    return f"Rule {rule} requires human review"


def build_handoff_packet(
    case_row: dict[str, Any],
    diagnosis: str,
    facts: dict[str, Any],
    verified_facts: list[str],
    actions_taken: list[dict[str, str]],
    rule_fired_text: str,
    trigger_id: str,
    confidence_obj: dict[str, Any] | None = None,
    cap: int = 5000,
    min_conf: float = 0.70,
    is_distress: bool = False,
    english_summary: str = "",
) -> dict[str, Any]:
    case_id = case_row["id"]
    language = case_row.get("language") or "en"
    owner_id = case_row.get("owner_id") or ""
    owner_display = "Our team" if not owner_id else f"{owner_id} from our support team"

    rec_action = RECOMMENDED_ACTION_BY_TRIGGER.get(
        trigger_id,
        "Review verified facts and approve or resolve.",
    )
    if trigger_id == "T8" and is_distress:
        rec_action += " Possible welfare concern: follow your urgent-escalation protocol."

    draft_template = get_template_text("ESCALATED", language)
    suggested_reply_draft = draft_template.format(case_id=case_id, owner=owner_display)

    amount = facts.get("amount") or facts.get("expected") or 0
    txn_id = facts.get("txn_id") or facts.get("refund_id") or ""
    summary = f"{diagnosis} for {case_row['persona_id']}" + (f" · {txn_id}" if txn_id else "") + (f" · ₹{amount:,}" if amount else "")

    conf_score = confidence_obj.get("score", 0.75) if confidence_obj else 0.75
    why_you = build_why_you_line(
        rule=trigger_id or case_row.get("rule_fired") or "4",
        agent_name=case_row.get("agent") or "payment_failure",
        amount=int(amount) if amount else 0,
        cap=cap,
        confidence_score=conf_score,
        min_conf=min_conf,
    )

    return {
        "case_ref": case_id,
        "case_id": case_id,
        "trigger_id": trigger_id,
        "lane": case_row.get("lane", "amber"),
        "language": language,
        "amount": int(amount) if amount else 0,
        "summary": summary,
        "why_you": why_you,
        "verified_facts": verified_facts,
        "checks": confidence_obj.get("checks", []) if confidence_obj else [],
        "actions_taken": actions_taken,
        "rule_fired": rule_fired_text,
        "recommended_action": rec_action,
        "confidence": confidence_obj or {
            "score": conf_score,
            "band": "medium",
            "understanding": 0.85,
            "evidence": 0.85,
            "policy": 0.30,
            "risk": 0.80,
            "checks": [],
        },
        "english_summary": english_summary or summary,
        "masked_text": case_row.get("masked_text") or "",
        "suggested_reply_draft": suggested_reply_draft,
    }

