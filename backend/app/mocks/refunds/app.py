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


def get_refunds_rows(limit: int = 8) -> list[dict[str, Any]]:
    recons = refunds_db.query_all(
        "SELECT id, ref_type, ref_id, case_id, user_id, status, created_at as updated_at, case_hint FROM reconciliations ORDER BY created_at DESC LIMIT 3"
    )
    rfs = refunds_db.query_all(
        "SELECT id, txn_id, user_id, amount, status, reason, updated_at, case_hint FROM refunds ORDER BY updated_at DESC LIMIT 6"
    )
    sts = refunds_db.query_all(
        "SELECT id, merchant_id, expected_amount, actual_amount, status, hold_reason, updated_at, case_hint FROM settlements ORDER BY updated_at DESC LIMIT 4"
    )
    combined: list[dict[str, Any]] = []
    for rc in recons:
        combined.append(
            {
                "id": rc["id"],
                "type": "recon",
                "amount": 0,
                "status": rc["status"],
                "hold_or_reason": f"{rc['ref_type']}:{rc['ref_id']}",
                "updated_at": rc["updated_at"],
                "case_id": rc["case_hint"] or rc["case_id"],
            }
        )
    for r in rfs:
        combined.append(
            {
                "id": r["id"],
                "type": "refund",
                "txn_id": r["txn_id"],
                "amount": r["amount"],
                "status": r["status"],
                "hold_or_reason": r["reason"] or r["txn_id"],
                "updated_at": r["updated_at"],
                "case_id": r["case_hint"],
            }
        )
    for s in sts:
        combined.append(
            {
                "id": s["id"],
                "type": "settlement",
                "amount": s["expected_amount"],
                "status": s["status"],
                "hold_or_reason": s["hold_reason"],
                "updated_at": s["updated_at"],
                "case_id": s["case_hint"],
            }
        )
    combined.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return combined[:limit]


def shift_refunds_time(hours: float) -> None:
    now = datetime.now(timezone.utc)
    rfs = refunds_db.query_all("SELECT id, txn_id, status, initiated_at, eta, updated_at FROM refunds")
    for r in rfs:
        new_init = shift_iso_ts(r["initiated_at"], hours)
        new_eta = shift_iso_ts(r["eta"], hours)
        new_upd = shift_iso_ts(r["updated_at"], hours)
        new_status = r["status"]
        completed_at = None
        if r["status"] in ("INITIATED", "PROCESSING") and new_eta:
            try:
                eta_dt = datetime.fromisoformat(new_eta)
                is_stuck = (r["id"] in refunds_sim.stuck_refund_ids) or (r["txn_id"] in refunds_sim.stuck_txn_ids)
                if eta_dt <= now and not is_stuck:
                    new_status = "COMPLETED"
                    completed_at = now.isoformat()
            except Exception:
                pass
        refunds_db.execute(
            "UPDATE refunds SET status = ?, initiated_at = ?, eta = ?, completed_at = COALESCE(completed_at, ?), updated_at = ? WHERE id = ?",
            (new_status, new_init, new_eta, completed_at, new_upd, r["id"]),
        )


refunds_app, refunds_sim = make_mock_app("refunds", refunds_db, get_refunds_rows, shift_refunds_time)


@refunds_app.get("/refunds")
async def get_refund_for_txn(
    txn_id: str = Query(...),
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    txn = ledger_db.query_one("SELECT id, user_id FROM transactions WHERE id = ?", (txn_id,))
    if not txn or txn["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    rows = refunds_db.query_all(
        "SELECT id, txn_id, user_id, amount, status, reason, initiated_at, eta, completed_at FROM refunds WHERE txn_id = ? AND user_id = ? ORDER BY initiated_at DESC",
        (txn_id, x_acting_user),
    )
    return rows


@refunds_app.get("/refunds/{refund_id}")
async def get_refund(
    refund_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    row = refunds_db.query_one(
        "SELECT id, txn_id, user_id, amount, status, reason, initiated_at, eta, completed_at FROM refunds WHERE id = ?",
        (refund_id,),
    )
    if not row or row["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return row


@refunds_app.get("/eligibility/{txn_id}")
async def check_eligibility(
    txn_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    txn = ledger_db.query_one(
        "SELECT id, user_id, amount, status, debit_status, bank_debit_status, credit_to_merchant FROM transactions WHERE id = ?",
        (txn_id,),
    )
    if not txn or txn["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})

    eligible = (
        txn["status"] in ("FAILED", "PENDING")
        and txn["debit_status"] == "DEBITED"
        and int(txn["credit_to_merchant"]) == 0
    )
    reason = "ELIGIBLE_FAILED_DEBIT" if eligible else "NOT_ELIGIBLE"
    return {"txn_id": txn_id, "eligible": eligible, "reason": reason}


@refunds_app.post("/refunds")
async def initiate_refund(
    request: Request,
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    txn_id = str(payload.get("txn_id", ""))
    amount = payload.get("amount")
    if not txn_id or amount is None:
        return JSONResponse(status_code=422, content={"error": "invalid"})
    amount = int(amount)

    # Check ownership FIRST (returns 404 before revealing amount mismatch)
    txn = ledger_db.query_one(
        "SELECT id, user_id, amount, status, debit_status, credit_to_merchant FROM transactions WHERE id = ?",
        (txn_id,),
    )
    if not txn or txn["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})

    # Check amount matches verified ledger transaction amount (returns 422)
    if int(txn["amount"]) != amount:
        return JSONResponse(status_code=422, content={"error": "invalid"})

    # Idempotency check
    if idempotency_key:
        existing = refunds_db.query_one(
            "SELECT id, txn_id, user_id, amount, status, reason, initiated_at, eta, completed_at FROM refunds WHERE idem_key = ?",
            (idempotency_key,),
        )
        if existing:
            if existing["user_id"] != x_acting_user or existing["txn_id"] != txn_id or int(existing["amount"]) != amount:
                return JSONResponse(status_code=409, content={"error": "idempotency_conflict"})
            return JSONResponse(status_code=200, content=existing)

    now = datetime.now(timezone.utc)
    eta = now + timedelta(hours=72)
    refund_id = next_id("refund")
    row = {
        "id": refund_id,
        "txn_id": txn_id,
        "user_id": x_acting_user,
        "amount": amount,
        "status": "INITIATED",
        "reason": "REFUND_DUE",
        "initiated_at": now.isoformat(),
        "eta": eta.isoformat(),
        "completed_at": None,
    }

    # Phantom write simulation: return 201 and an ID, but persist nothing and do not store idem_key
    if getattr(request.state, "is_phantom", False):
        return JSONResponse(status_code=201, content=row)

    refunds_db.execute(
        """
        INSERT INTO refunds(id, txn_id, user_id, amount, status, reason, idem_key, initiated_at, eta, completed_at, updated_at, case_hint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            row["txn_id"],
            row["user_id"],
            row["amount"],
            row["status"],
            row["reason"],
            idempotency_key or "",
            row["initiated_at"],
            row["eta"],
            None,
            now.isoformat(),
            x_case_id or "",
        ),
    )
    bus.publish_system_change("refunds", "refunds", refund_id, x_case_id)
    return JSONResponse(status_code=201, content=row)


@refunds_app.get("/settlements")
async def get_settlements(
    merchant_id: str | None = Query(default=None),
    latest: bool = Query(default=True),
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    target_merchant = merchant_id or x_acting_user
    if target_merchant != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})

    rows = refunds_db.query_all(
        "SELECT id, merchant_id, expected_amount, actual_amount, status, hold_reason, due_date FROM settlements WHERE merchant_id = ? ORDER BY due_date DESC",
        (x_acting_user,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return rows[0] if latest else rows


@refunds_app.get("/calendar/next-working-day")
async def next_working_day(
    from_date: str | None = Query(default=None, alias="from"),
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    if from_date:
        try:
            dt = datetime.fromisoformat(from_date)
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    holidays = {r["date_str"] for r in refunds_db.query_all("SELECT date_str FROM bank_holidays")}
    candidate = dt + timedelta(days=1)
    for _ in range(14):
        d_str = candidate.strftime("%Y-%m-%d")
        if candidate.weekday() not in (5, 6) and d_str not in holidays:
            break
        candidate += timedelta(days=1)

    return {
        "next_working_day": candidate.strftime("%Y-%m-%d"),
        "formatted": candidate.strftime("%d %b"),
    }


@refunds_app.post("/reconciliations")
async def raise_reconciliation(
    request: Request,
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    ref_type = str(payload.get("ref_type", "REFUND"))
    ref_id = str(payload.get("ref_id", ""))
    case_id = str(payload.get("case_id", x_case_id or ""))

    recon_id = next_id("recon")
    now_iso = utc_now_iso()
    row = {
        "id": recon_id,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "case_id": case_id,
        "user_id": x_acting_user,
        "status": "OPEN",
        "created_at": now_iso,
    }
    if getattr(request.state, "is_phantom", False):
        return JSONResponse(status_code=201, content=row)

    refunds_db.execute(
        "INSERT INTO reconciliations(id, ref_type, ref_id, case_id, user_id, status, created_at, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (recon_id, ref_type, ref_id, case_id, x_acting_user, "OPEN", now_iso, case_id),
    )
    bus.publish_system_change("refunds", "reconciliations", recon_id, case_id)
    return JSONResponse(status_code=201, content=row)


@refunds_app.get("/reconciliations/{recon_id}")
async def get_reconciliation(
    recon_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    row = refunds_db.query_one(
        "SELECT id, ref_type, ref_id, case_id, user_id, status, created_at FROM reconciliations WHERE id = ?",
        (recon_id,),
    )
    if not row or row["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return row

