"""Tool execution dispatcher for Saathi v6.0."""
from __future__ import annotations

from typing import Any

from app.tools import crm, ledger, notify, refunds
from app.tools.client import ToolOutcome


async def execute_action(
    *,
    action_name: str,
    args: dict[str, Any],
    acting_user: str,
    case_id: str,
    actor: str = "saathi",
    idempotency_key: str | None = None,
) -> ToolOutcome:
    if action_name == "initiate_refund":
        txn_id = str(args.get("txn_id", ""))
        amount = int(args.get("amount", 0))
        idem = idempotency_key or f"{case_id}|initiate_refund|{txn_id}"
        return await refunds.initiate_refund(
            acting_user=acting_user,
            txn_id=txn_id,
            amount=amount,
            case_id=case_id,
            idempotency_key=idem,
            actor=actor,
        )

    if action_name == "raise_reconciliation":
        ref_type = str(args.get("ref_type", "REFUND"))
        ref_id = str(args.get("ref_id", ""))
        idem = idempotency_key or f"{case_id}|raise_reconciliation|{ref_id}"
        return await refunds.raise_reconciliation(
            acting_user=acting_user,
            ref_type=ref_type,
            ref_id=ref_id,
            case_id=case_id,
            idempotency_key=idem,
            actor=actor,
        )

    if action_name == "lock_payment_instrument":
        instrument = str(args.get("instrument", "UPI"))
        hours = int(args.get("hours", 24))
        reason = str(args.get("reason", "FRAUD_SIGNAL"))
        idem = idempotency_key or f"{case_id}|lock_payment_instrument|{acting_user}"
        return await ledger.lock_payment_instrument(
            acting_user=acting_user,
            instrument=instrument,
            hours=hours,
            reason=reason,
            case_id=case_id,
            idempotency_key=idem,
            actor=actor,
        )

    if action_name == "create_ticket":
        category = str(args.get("category", "GENERAL"))
        details = args.get("details") or {}
        idem = idempotency_key or f"{case_id}|create_ticket|{category}"
        return await crm.create_ticket(
            acting_user=acting_user,
            case_id=case_id,
            category=category,
            details=details,
            idempotency_key=idem,
            actor=actor,
        )

    if action_name == "schedule_followup":
        run_in_minutes = int(args.get("run_in_minutes", 360))
        check_kind = str(args.get("check", "REFUND_COMPLETED"))
        return await notify.schedule_followup(
            acting_user=acting_user,
            case_id=case_id,
            run_in_minutes=run_in_minutes,
            check_kind=check_kind,
            actor=actor,
        )

    return ToolOutcome(
        ok=False,
        status="rejected",
        http_status=400,
        error=f"unknown_action:{action_name}",
    )
