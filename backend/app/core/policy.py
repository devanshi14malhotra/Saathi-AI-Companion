import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import PolicyConfig, get_ablate_flags, is_break_policy
from app.db.core import query_all

TRIGGER_ORDER = ["T1", "T8", "T4", "T3", "T5", "T6", "T2", "T7", "KS"]

TRIGGER_TEXT = {
    "T1": "Fraud signal present",
    "T2": "Customer asked for a human",
    "T3": "Evidence conflict persists after one re-check",
    "T4": "Compliance or risk hold",
    "T5": "Money amount above the ceiling",
    "T6": "Tool failure after 2 retries",
    "T7": "Ambiguity unresolved after the one clarifying question",
    "T8": "Sensitive or vulnerable case (legal, regulatory, abuse, distress)",
    "KS": "Agent paused by kill switch",
}


@dataclass
class ProposedAction:
    name: str
    args: dict[str, Any]
    is_money: bool
    amount: int = 0
    target_txn: str | None = None
    target_user: str = ""


@dataclass
class CasePolicyContext:
    case_id: str
    persona_user: str
    triggers: list[str] = field(default_factory=list)
    confidence: float = 1.0
    velocity_count_24h: int | None = None
    velocity_amount_24h: int | None = None


@dataclass
class Decision:
    outcome: str  # AUTO | APPROVE | ESCALATE | BLOCK
    rule: str     # "1", "3", "3v", "3c", "4", "5", or trigger id
    text: str


def get_persona_auto_velocity_24h(persona_id: str) -> tuple[int, int]:
    """Counts AUTO refunds and sum of amounts for this persona in the last 24h from audit_log."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = query_all(
        """
        SELECT a.params_json, a.result_json
        FROM audit_log a
        JOIN cases c ON a.case_id = c.id
        WHERE c.persona_id = ?
          AND a.action = 'initiate_refund'
          AND a.actor = 'saathi'
          AND a.ts >= ?
        """,
        (persona_id, cutoff),
    )
    count = 0
    total_amt = 0
    seen_txns: set[str] = set()
    for r in rows:
        try:
            res = json.loads(r["result_json"] or "{}")
            params = json.loads(r["params_json"] or "{}")
            if res.get("outcome") == "success" or res.get("status") in ("INITIATED", "PROCESSING", "COMPLETED"):
                txn_id = params.get("txn_id") or res.get("body", {}).get("txn_id")
                amt = int(params.get("amount") or res.get("body", {}).get("amount") or 0)
                if txn_id and txn_id not in seen_txns:
                    seen_txns.add(txn_id)
                    count += 1
                    total_amt += amt
        except Exception:
            pass
    return count, total_amt


def evaluate(case: CasePolicyContext, action: ProposedAction | None, agent: Any, cfg: PolicyConfig) -> Decision:
    ablate = get_ablate_flags()

    # 1. Allowlist check, then target_user check (Rule 1 — never disabled)
    if action and action.name not in agent.ALLOWLIST:
        return Decision("BLOCK", "1", "Rule 1 · action not allowed for this agent")
    if action and action.target_user and action.target_user != case.persona_user:
        return Decision("BLOCK", "1", "Rule 1 · other user's data")

    # Eval ablation: no_policy disables everything except allowlist/ownership
    if "no_policy" in ablate:
        if action and action.is_money:
            return Decision("AUTO", "3", f"Rule 3 (ablated no_policy) · money action ₹{action.amount:,} → AUTO")
        return Decision("AUTO", "5", "Rule 5 · informational / non-money action → AUTO")

    # 2. Triggers present (including T8, KS): ESCALATE by TRIGGER_ORDER
    if case.triggers:
        valid_triggers = [t for t in case.triggers if t in TRIGGER_ORDER]
        if valid_triggers:
            t = sorted(valid_triggers, key=TRIGGER_ORDER.index)[0]
            return Decision("ESCALATE", t, f"Rule 2 · {t} · {TRIGGER_TEXT[t]}")

    # 3. Money amount above ceiling: T5
    if action and action.is_money and action.amount > cfg.ceiling:
        return Decision("ESCALATE", "T5", f"Rule 2 · T5 · ₹{action.amount:,} above ceiling ₹{cfg.ceiling:,}")

    # 4. Money action rules (4, 3v, 3c, 3)
    if action and action.is_money:
        agent_name = getattr(agent, "NAME", "payment_failure")
        mode = cfg.autonomy.get(agent_name, "guarded")
        cap = cfg.modes.get(mode, {"auto_cap": 5000})["auto_cap"]

        # Eval-only --break-policy switch: makes Rule 4 return AUTO to prove harness catches wrong auto-actions
        if action.amount > cap:
            if is_break_policy():
                return Decision("AUTO", "3", f"Rule 3 (BREAK_POLICY) · ₹{action.amount:,} forced AUTO")
            return Decision("APPROVE", "4", f"Rule 4 · ₹{action.amount:,} > auto-cap ₹{cap:,} ({mode}) → needs approval")

        # Velocity check (Rule 3v)
        v_count = case.velocity_count_24h
        v_amount = case.velocity_amount_24h
        if v_count is None or v_amount is None:
            v_count, v_amount = get_persona_auto_velocity_24h(case.persona_user)
        if v_count >= cfg.velocity_max_auto_refunds_24h or (v_amount + action.amount) > cfg.velocity_max_auto_amount_24h:
            return Decision("APPROVE", "3v", "Rule 3v · velocity limit reached → needs approval")

        # Confidence gate (Rule 3c)
        if "no_gate" not in ablate and case.confidence < cfg.min_auto_confidence:
            return Decision(
                "APPROVE",
                "3c",
                f"Rule 3c · confidence {case.confidence:.2f} below {cfg.min_auto_confidence:.2f} → needs approval",
            )

        return Decision("AUTO", "3", f"Rule 3 · money action ₹{action.amount:,} ≤ auto-cap ₹{cap:,} ({mode}) → AUTO")

    # 5. Otherwise Rule 5 AUTO
    return Decision("AUTO", "5", "Rule 5 · informational / non-money action → AUTO")

