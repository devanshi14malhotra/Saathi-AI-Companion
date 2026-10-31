"""Ledger tool wrappers with guard scanning on customer-controlled remark field."""
from __future__ import annotations

from typing import Any

from app.core.config import get_ablate_flags
from app.core.guard import scan as guard_scan
from app.tools.client import ToolOutcome, call_service, record_case_event


def sanitize_txn_row(row: dict[str, Any], case_id: str | None = None) -> dict[str, Any]:
    out = dict(row)
    raw_remark = str(out.pop("remark", "") or "")
    ablate = get_ablate_flags()
    if "no_guard" in ablate:
        out["remark_clean"] = raw_remark
        out["remark_flagged"] = False
        out["remark_removed"] = []
    else:
        clean_text, hit, removed = guard_scan(raw_remark)
        out["remark_clean"] = clean_text
        out["remark_flagged"] = bool(hit)
        out["remark_removed"] = removed
        if hit and case_id:
            record_case_event(
                case_id=case_id,
                badge="[GUARD]",
                evt_type="remark_flagged",
                summary=f"Sanitized untrusted ledger remark on {out.get('id')}",
                payload={"txn_id": out.get("id"), "removed": removed, "remark_clean": clean_text},
                status="warn",
            )
    return out


async def lookup_transaction(
    *,
    acting_user: str,
    txn_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    res = await call_service(
        service="ledger",
        tool_name="lookup_transaction",
        method="GET",
        path=f"/transactions/{txn_id}",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
    )
    if res.ok and isinstance(res.data, dict):
        res.data = sanitize_txn_row(res.data, case_id=case_id)
    return res


async def search_transactions_by_amount(
    *,
    acting_user: str,
    amount: int,
    days: int = 7,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    res = await call_service(
        service="ledger",
        tool_name="search_transactions_by_amount",
        method="GET",
        path="/transactions/search",
        acting_user=acting_user,
        params={"amount": amount, "days": days},
        case_id=case_id,
        actor=actor,
    )
    if res.ok and isinstance(res.data, list):
        res.data = [sanitize_txn_row(r, case_id=case_id) for r in res.data]
    return res


async def list_recent_transactions(
    *,
    acting_user: str,
    limit: int = 5,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    res = await call_service(
        service="ledger",
        tool_name="list_recent_transactions",
        method="GET",
        path="/transactions",
        acting_user=acting_user,
        params={"limit": limit},
        case_id=case_id,
        actor=actor,
    )
    if res.ok and isinstance(res.data, list):
        res.data = [sanitize_txn_row(r, case_id=case_id) for r in res.data]
    return res


async def get_bank_status(
    *,
    acting_user: str,
    txn_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="ledger",
        tool_name="get_bank_status",
        method="GET",
        path=f"/transactions/{txn_id}/bank-status",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
    )


async def lock_payment_instrument(
    *,
    acting_user: str,
    instrument: str = "UPI",
    hours: int = 24,
    reason: str = "FRAUD_SIGNAL",
    case_id: str | None = None,
    idempotency_key: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="ledger",
        tool_name="lock_payment_instrument",
        method="POST",
        path="/locks",
        acting_user=acting_user,
        json_body={"instrument": instrument, "hours": hours, "reason": reason},
        idempotency_key=idempotency_key or (f"{case_id}|lock_payment_instrument|{acting_user}" if case_id else None),
        case_id=case_id,
        actor=actor,
    )


async def get_locks(
    *,
    acting_user: str,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = False,
) -> ToolOutcome:
    return await call_service(
        service="ledger",
        tool_name="get_locks",
        method="GET",
        path="/locks",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )
