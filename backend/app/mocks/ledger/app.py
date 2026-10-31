from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Header, Query, Request
from fastapi.responses import JSONResponse

from app.core.events import bus
from app.core.ids import next_id
from app.db.core import utc_now_iso
from app.mocks.common import make_mock_app, shift_iso_ts
from app.mocks.ledger.db import ledger_db
from app.mocks.refunds.db import refunds_db


def get_ledger_rows(limit: int = 8) -> list[dict[str, Any]]:
    locks = ledger_db.query_all(
        "SELECT id, user_id, instrument, status, reason, created_at, case_hint FROM locks ORDER BY created_at DESC LIMIT 3"
    )
    txns = ledger_db.query_all(
        """
        SELECT id, user_id, amount, counterparty, status, debit_status, bank_debit_status,
               credit_to_merchant, reversal_status, rail, remark, updated_at, case_hint
        FROM transactions
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    out: list[dict[str, Any]] = []
    for lk in locks:
        out.append(
            {
                "id": lk["id"],
                "txn_id": lk["id"],
                "user_id": lk["user_id"],
                "amount": 0,
                "counterparty": f"LOCK:{lk['instrument']}",
                "status": "LOCKED",
                "debit_status": lk["status"],
                "credit_to_merchant": 0,
                "reversal_status": lk["reason"],
                "rail": "SECURITY",
                "remark": "",
                "case_id": lk["case_hint"],
            }
        )
    for t in txns:
        out.append(
            {
                "id": t["id"],
                "txn_id": t["id"],
                "user_id": t["user_id"],
                "amount": t["amount"],
                "counterparty": t["counterparty"],
                "status": t["status"],
                "debit_status": t["debit_status"],
                "bank_debit_status": t["bank_debit_status"],
                "credit_to_merchant": t["credit_to_merchant"],
                "reversal_status": t["reversal_status"],
                "rail": t["rail"],
                "remark": t["remark"],
                "case_id": t["case_hint"],
            }
        )
    return out[:limit]


def shift_ledger_time(hours: float) -> None:
    rows = ledger_db.query_all("SELECT id, created_at, updated_at, reversal_eta FROM transactions")
    for r in rows:
        ledger_db.execute(
            "UPDATE transactions SET created_at = ?, updated_at = ?, reversal_eta = ? WHERE id = ?",
            (
                shift_iso_ts(r["created_at"], hours),
                shift_iso_ts(r["updated_at"], hours),
                shift_iso_ts(r["reversal_eta"], hours),
                r["id"],
            ),
        )
    locks = ledger_db.query_all("SELECT id, created_at, expires_at FROM locks")
    for lk in locks:
        ledger_db.execute(
            "UPDATE locks SET created_at = ?, expires_at = ? WHERE id = ?",
            (shift_iso_ts(lk["created_at"], hours), shift_iso_ts(lk["expires_at"], hours), lk["id"]),
        )


ledger_app, ledger_sim = make_mock_app("ledger", ledger_db, get_ledger_rows, shift_ledger_time)


@ledger_app.get("/transactions")
async def list_transactions(
    limit: int = Query(default=5, ge=1, le=50),
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    rows = ledger_db.query_all(
        """
        SELECT id, user_id, amount, counterparty, status, debit_status, bank_debit_status,
               credit_to_merchant, bank_code, reversal_status, reversal_eta, rail, remark, created_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (x_acting_user, limit),
    )
    return rows


@ledger_app.get("/transactions/search")
async def search_transactions(
    amount: int = Query(...),
    days: int = Query(default=7),
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = ledger_db.query_all(
        """
        SELECT id, user_id, amount, counterparty, status, debit_status, bank_debit_status,
               credit_to_merchant, bank_code, reversal_status, reversal_eta, rail, remark, created_at
        FROM transactions
        WHERE user_id = ? AND amount = ? AND created_at >= ?
        ORDER BY created_at DESC
        """,
        (x_acting_user, amount, cutoff),
    )
    return rows


@ledger_app.get("/transactions/{txn_id}")
async def get_transaction(
    txn_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default=None, alias="X-Case-Id"),
):
    row = ledger_db.query_one(
        """
        SELECT id, user_id, amount, counterparty, status, debit_status, bank_debit_status,
               credit_to_merchant, bank_code, reversal_status, reversal_eta, rail, remark, created_at
        FROM transactions
        WHERE id = ?
        """,
        (txn_id,),
    )
    if not row or row["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    if x_case_id:
        ledger_db.execute(
            "UPDATE transactions SET case_hint = ?, updated_at = ? WHERE id = ?",
            (x_case_id, utc_now_iso(), txn_id),
        )
    return row


@ledger_app.get("/transactions/{txn_id}/bank-status")
async def get_bank_status(
    txn_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    row = ledger_db.query_one(
        "SELECT id, user_id, bank_debit_status, bank_code FROM transactions WHERE id = ?",
        (txn_id,),
    )
    if not row or row["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return {
        "txn_id": row["id"],
        "bank_debit_status": row["bank_debit_status"],
        "bank_code": row["bank_code"],
    }


@ledger_app.post("/locks")
async def create_lock(
    request: Request,
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    instrument = str(payload.get("instrument", "UPI"))
    hours = int(payload.get("hours", 24))
    reason = str(payload.get("reason", "FRAUD_SIGNAL"))

    if idempotency_key:
        existing = ledger_db.query_one("SELECT * FROM locks WHERE idem_key = ? AND user_id = ?", (idempotency_key, x_acting_user))
        if existing:
            return JSONResponse(status_code=200, content=existing)

    now = datetime.now(timezone.utc)
    while True:
        lock_id = next_id("lock")
        if not ledger_db.query_one("SELECT id FROM locks WHERE id = ?", (lock_id,)):
            break
    expires_at = (now + timedelta(hours=hours)).isoformat()
    row = {
        "id": lock_id,
        "user_id": x_acting_user,
        "instrument": instrument,
        "hours": hours,
        "reason": reason,
        "status": "ACTIVE",
        "idem_key": idempotency_key or "",
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "case_hint": x_case_id or "",
    }
    if getattr(request.state, "is_phantom", False):
        return JSONResponse(status_code=201, content=row)

    ledger_db.execute(
        """
        INSERT INTO locks(id, user_id, instrument, hours, reason, status, idem_key, created_at, expires_at, case_hint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["user_id"],
            row["instrument"],
            row["hours"],
            row["reason"],
            row["status"],
            row["idem_key"],
            row["created_at"],
            row["expires_at"],
            row["case_hint"],
        ),
    )
    bus.publish_system_change("ledger", "locks", lock_id, x_case_id)
    return JSONResponse(status_code=201, content=row)


@ledger_app.get("/locks")
async def get_locks(
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    rows = ledger_db.query_all(
        "SELECT id, user_id, instrument, hours, reason, status, created_at, expires_at FROM locks WHERE user_id = ? ORDER BY created_at DESC",
        (x_acting_user,),
    )
    return rows


@ledger_app.get("/ops/affected")
async def ops_affected(
    bank_code: str | None = Query(default=None),
    since_hours: float = Query(default=48.0),
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_actor: str = Header(default="", alias="X-Actor"),
):
    # SPEC_V6 §5.6: Requires X-Acting-User: OPS and X-Actor starting 'incident-monitor' or 'human:'; anything else returns 403.
    if x_acting_user != "OPS" or not (x_actor.startswith("incident-monitor") or x_actor.startswith("human:")):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    if bank_code:
        rows = ledger_db.query_all(
            """
            SELECT id, user_id, amount, counterparty, created_at, rail, bank_code
            FROM transactions
            WHERE status = 'FAILED' AND debit_status = 'DEBITED' AND credit_to_merchant = 0
              AND bank_code = ? AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (bank_code, cutoff),
        )
    else:
        rows = ledger_db.query_all(
            """
            SELECT id, user_id, amount, counterparty, created_at, rail, bank_code
            FROM transactions
            WHERE status = 'FAILED' AND debit_status = 'DEBITED' AND credit_to_merchant = 0
              AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (cutoff,),
        )

    out = []
    for r in rows:
        rf = refunds_db.query_one("SELECT id FROM refunds WHERE txn_id = ?", (r["id"],))
        out.append(
            {
                "txn_id": r["id"],
                "user_id": r["user_id"],
                "amount": r["amount"],
                "counterparty": r["counterparty"],
                "created_at": r["created_at"],
                "has_refund": bool(rf),
                "rail": r["rail"],
                "bank_code": r["bank_code"],
            }
        )
    return out

