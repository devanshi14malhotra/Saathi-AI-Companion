from app.core.events import bus
from app.db.core import execute, query_one, utc_now_iso

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"UNDERSTANDING", "ROUTED", "CLARIFYING", "DIAGNOSING", "POLICY_CHECK", "EXECUTING", "AWAITING_APPROVAL", "ESCALATED", "BLOCKED", "OUTCOME_VERIFIED", "CLOSED"},
    "UNDERSTANDING": {"ROUTED", "CLARIFYING", "DIAGNOSING", "ESCALATED", "BLOCKED", "CLOSED"},
    "ROUTED": {"CLARIFYING", "DIAGNOSING", "POLICY_CHECK", "ESCALATED", "BLOCKED", "CLOSED"},
    "CLARIFYING": {"UNDERSTANDING", "ROUTED", "DIAGNOSING", "POLICY_CHECK", "ESCALATED", "BLOCKED", "CLOSED"},
    "DIAGNOSING": {"CLARIFYING", "POLICY_CHECK", "EXECUTING", "AWAITING_APPROVAL", "ESCALATED", "BLOCKED", "OUTCOME_VERIFIED", "CLOSED"},
    "POLICY_CHECK": {"EXECUTING", "AWAITING_APPROVAL", "ESCALATED", "BLOCKED", "OUTCOME_VERIFIED", "CLOSED"},
    "EXECUTING": {"OUTCOME_VERIFIED", "ESCALATED", "CLOSED"},
    "OUTCOME_VERIFIED": {"CLOSED", "ESCALATED"},
    "AWAITING_APPROVAL": {"EXECUTING", "OUTCOME_VERIFIED", "ESCALATED", "CLOSED"},
    "ESCALATED": {"ESCALATED", "ROUTED", "DIAGNOSING", "CLOSED"},
    "BLOCKED": {"CLOSED"},
    "CLOSED": {"REOPENED", "UNDERSTANDING"},
    "REOPENED": {"UNDERSTANDING", "ROUTED", "DIAGNOSING", "ESCALATED", "CLOSED"},
}


def transition(case_id: str, new_state: str) -> dict:
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not row:
        raise ValueError(f"Case {case_id} not found")
    cur_state = row["state"]
    if cur_state != new_state:
        allowed = ALLOWED_TRANSITIONS.get(cur_state, set())
        if new_state not in allowed:
            raise ValueError(f"Illegal state transition for {case_id}: {cur_state} -> {new_state}")
    now_iso = utc_now_iso()
    if new_state == "CLOSED":
        execute("UPDATE cases SET state = ?, closed_at = ? WHERE id = ?", (new_state, now_iso, case_id))
    elif new_state == "REOPENED":
        execute("UPDATE cases SET state = ?, reopened = 1 WHERE id = ?", (new_state, case_id))
    else:
        execute("UPDATE cases SET state = ? WHERE id = ?", (new_state, case_id))
    updated = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) or {}
    bus.publish_console("case_updated", {"case": updated})
    return updated

