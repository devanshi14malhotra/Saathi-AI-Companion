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
import concurrent.futures
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
from app.core.orchestrator import handle_message, get_case_detail, build_case_receipt, decide_approval


def init_app_state() -> None:
    """Initializes databases and syncs counter sequences."""
    try:
        from app.main import ensure_all_dbs_initialized
        ensure_all_dbs_initialized()
    except Exception:
        pass
    sync_id_counters(get_core_conn())


def run_async(coro: Any) -> Any:
    """Safely runs an async coroutine inside Streamlit thread, supporting nested/running event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def get_all_personas() -> list[dict[str, Any]]:
    """Fetches real customers from CRM DB, returning an empty list gracefully if none exist."""
    try:
        return crm_db.query_all("SELECT * FROM customers ORDER BY id ASC") or []
    except Exception:
        return []


def get_user_transactions(user_id: str) -> list[dict[str, Any]]:
    """Fetches live ledger transactions for a user."""
    try:
        return ledger_db.query_all(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ) or []
    except Exception:
        return []


def get_all_transactions(limit: int = 50) -> list[dict[str, Any]]:
    """Fetches global transactions from ledger DB."""
    try:
        return ledger_db.query_all(f"SELECT * FROM transactions ORDER BY created_at DESC LIMIT {limit}") or []
    except Exception:
        return []


def get_all_refunds(limit: int = 50) -> list[dict[str, Any]]:
    """Fetches live refunds from refunds DB."""
    try:
        return refunds_db.query_all(f"SELECT * FROM refunds ORDER BY initiated_at DESC LIMIT {limit}") or []
    except Exception:
        return []


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


def get_live_metrics() -> dict[str, Any]:
    """Computes real metrics directly from live SQLite tables."""
    total_cases_res = query_core_one("SELECT COUNT(*) as c FROM cases")
    total_cases = total_cases_res["c"] if total_cases_res else 0

    auto_res = query_core_one("SELECT COUNT(*) as c FROM cases WHERE outcome = 'AUTO'")
    auto_resolved = auto_res["c"] if auto_res else 0

    esc_res = query_core_one("SELECT COUNT(*) as c FROM cases WHERE outcome IN ('ESCALATE', 'APPROVE')")
    escalated = esc_res["c"] if esc_res else 0
    
    total_refunds_res = refunds_db.query_one("SELECT COUNT(*) as c, COALESCE(SUM(amount), 0) as s FROM refunds")
    refund_count = total_refunds_res["c"] if total_refunds_res else 0
    refund_amount = total_refunds_res["s"] if total_refunds_res else 0

    comp_res = query_core_one("SELECT COUNT(*) as c, COALESCE(SUM(amount_estimate), 0) as s FROM compensation_claims")
    comp_count = comp_res["c"] if comp_res else 0
    comp_amount = comp_res["s"] if comp_res else 0

    rate = (auto_resolved / total_cases * 100) if total_cases > 0 else 0.0

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
