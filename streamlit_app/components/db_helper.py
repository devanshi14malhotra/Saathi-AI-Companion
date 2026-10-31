"""
Database and Core Engine Helper for Saathi Streamlit App.
Provides clean query wrappers across the 5 isolated microservice databases:
1. core.db (cases, approvals, claims, events)
2. ledger.db (users, transactions, locks)
3. refunds.db (refunds, reconciliations, settlements)
4. crm.db (customers, tickets, handoffs)
5. notify.db (outbox, followups)
"""

import asyncio
from typing import Any
import sys
from pathlib import Path

# Ensure backend is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.core import get_conn as get_core_conn, query_all as query_core_all, query_one as query_core_one, sync_id_counters, execute as execute_core
from app.mocks.ledger.db import ledger_db
from app.mocks.refunds.db import refunds_db
from app.mocks.crm.db import crm_db
from app.mocks.notify.db import notify_db
from app.core.orchestrator import handle_message, get_case_detail, build_case_receipt


def init_app_state() -> None:
    """Ensures database connections and counter sequences are synced."""
    sync_id_counters(get_core_conn())


def run_async(coro: Any) -> Any:
    """Safely runs an async coroutine inside Streamlit thread."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        # Inside nested loop
        new_loop = asyncio.new_event_loop()
        return new_loop.run_until_complete(coro)
    return loop.run_until_complete(coro)


def get_all_personas() -> list[dict[str, Any]]:
    """Fetches real customers from CRM DB."""
    return crm_db.query_all("SELECT * FROM customers ORDER BY id ASC")


def get_user_transactions(user_id: str) -> list[dict[str, Any]]:
    """Fetches live ledger transactions for a user."""
    return ledger_db.query_all(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )


def get_all_transactions(limit: int = 50) -> list[dict[str, Any]]:
    """Fetches global transactions from ledger DB."""
    return ledger_db.query_all(f"SELECT * FROM transactions ORDER BY created_at DESC LIMIT {limit}")


def get_all_refunds(limit: int = 50) -> list[dict[str, Any]]:
    """Fetches live refunds from refunds DB."""
    return refunds_db.query_all(f"SELECT * FROM refunds ORDER BY initiated_at DESC LIMIT {limit}")


def get_pending_approvals() -> list[dict[str, Any]]:
    """Fetches human-in-the-loop escalations and approval requests."""
    return query_core_all(
        """
        SELECT a.*, c.persona_id, c.agent, c.intent, c.diagnosis, c.confidence, c.rule_fired
        FROM approvals a
        LEFT JOIN cases c ON a.case_id = c.id
        WHERE a.status = 'PENDING'
        ORDER BY a.created_at DESC
        """
    )


def get_all_escalations() -> list[dict[str, Any]]:
    """Fetches all escalated cases."""
    return query_core_all(
        """
        SELECT * FROM cases 
        WHERE outcome = 'ESCALATE' OR lane = 'amber'
        ORDER BY id DESC LIMIT 50
        """
    )


def resolve_approval(approval_id: str, action_decision: str, reviewer: str = "Support Lead") -> bool:
    """Executes human approval decision in core and updates downstream microservice."""
    row = query_core_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if not row:
        return False

    import json
    action_data = json.loads(row.get("proposed_action_json") or "{}")
    case_id = row.get("case_id", "")
    new_status = "APPROVED" if action_decision == "APPROVE" else "REJECTED"

    execute_core(
        "UPDATE approvals SET status = ?, reviewed_by = ?, reviewed_at = datetime('now') WHERE id = ?",
        (new_status, reviewer, approval_id),
    )

    if action_decision == "APPROVE":
        execute_core(
            "UPDATE cases SET outcome = 'RESOLVED', state = 'CLOSED' WHERE id = ?",
            (case_id,),
        )
        # If proposed action was refund, execute it in refunds.db
        act_name = action_data.get("name") or action_data.get("action")
        if act_name == "initiate_refund":
            txn_id = action_data.get("args", {}).get("transaction_id") or action_data.get("transaction_id", "")
            amt = int(action_data.get("args", {}).get("amount") or action_data.get("amount", 0))
            if txn_id and amt:
                from app.core.ids import next_id
                rf_id = next_id("refund")
                refunds_db.execute(
                    """
                    INSERT INTO refunds(id, txn_id, user_id, amount, status, reason, initiated_at, eta)
                    VALUES (?, ?, ?, ?, 'INITIATED', 'Human Approved Escalation', datetime('now'), datetime('now', '+24 hours'))
                    """,
                    (rf_id, txn_id, row.get("persona_id", ""), amt),
                )
    else:
        execute_core(
            "UPDATE cases SET outcome = 'REJECTED_BY_HUMAN', state = 'CLOSED' WHERE id = ?",
            (case_id,),
        )

    return True


def get_live_metrics() -> dict[str, Any]:
    """Computes real metrics directly from live SQLite tables."""
    total_cases = query_core_one("SELECT COUNT(*) as c FROM cases")["c"]
    auto_resolved = query_core_one("SELECT COUNT(*) as c FROM cases WHERE outcome = 'AUTO'")["c"]
    escalated = query_core_one("SELECT COUNT(*) as c FROM cases WHERE outcome = 'ESCALATE'")["c"]
    
    total_refunds_res = refunds_db.query_one("SELECT COUNT(*) as c, COALESCE(SUM(amount), 0) as s FROM refunds")
    refund_count = total_refunds_res["c"]
    refund_amount = total_refunds_res["s"]

    comp_res = query_core_one("SELECT COUNT(*) as c, COALESCE(SUM(amount_estimate), 0) as s FROM compensation_claims")
    comp_count = comp_res["c"] if comp_res else 0
    comp_amount = comp_res["s"] if comp_res else 0

    rate = (auto_resolved / total_cases * 100) if total_cases > 0 else 100.0

    return {
        "total_cases": total_cases,
        "auto_resolved": auto_resolved,
        "escalated": escalated,
        "auto_rate": round(rate, 1),
        "refund_count": refund_count,
        "refund_amount": refund_amount,
        "comp_count": comp_count,
        "comp_amount": comp_amount,
    }
