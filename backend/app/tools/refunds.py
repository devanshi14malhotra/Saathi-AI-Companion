"""Refunds & Settlements tool wrappers matching app/mocks/refunds/app.py."""
from __future__ import annotations

from app.tools.client import ToolOutcome, call_service


async def get_refund_for_txn(
    *,
    acting_user: str,
    txn_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = True,
) -> ToolOutcome:
    return await call_service(
        service="refunds",
        tool_name="get_refund_for_txn",
        method="GET",
        path="/refunds",
        acting_user=acting_user,
        params={"txn_id": txn_id},
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )


async def get_refund(
    *,
    acting_user: str,
    refund_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = True,
) -> ToolOutcome:
    return await call_service(
        service="refunds",
        tool_name="get_refund",
        method="GET",
        path=f"/refunds/{refund_id}",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )


async def check_refund_eligibility(
    *,
    acting_user: str,
    txn_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="refunds",
        tool_name="check_refund_eligibility",
        method="GET",
        path=f"/eligibility/{txn_id}",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
    )


async def initiate_refund(
    *,
    acting_user: str,
    txn_id: str,
    amount: int,
    case_id: str | None = None,
    idempotency_key: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    idem = idempotency_key or (f"{case_id}|initiate_refund|{txn_id}" if case_id else None)
    return await call_service(
        service="refunds",
        tool_name="initiate_refund",
        method="POST",
        path="/refunds",
        acting_user=acting_user,
        json_body={"txn_id": txn_id, "amount": int(amount)},
        idempotency_key=idem,
        case_id=case_id,
        actor=actor,
    )


async def get_settlement_batch(
    *,
    acting_user: str,
    merchant_id: str | None = None,
    latest: bool = True,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="refunds",
        tool_name="get_settlement_batch",
        method="GET",
        path="/settlements",
        acting_user=acting_user,
        params={"merchant_id": merchant_id or acting_user, "latest": latest},
        case_id=case_id,
        actor=actor,
    )


async def next_working_day(
    *,
    acting_user: str,
    from_date: str | None = None,
    case_id: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    params = {"from": from_date} if from_date else None
    return await call_service(
        service="refunds",
        tool_name="next_working_day",
        method="GET",
        path="/calendar/next-working-day",
        acting_user=acting_user,
        params=params,
        case_id=case_id,
        actor=actor,
    )


async def raise_reconciliation(
    *,
    acting_user: str,
    ref_type: str,
    ref_id: str,
    case_id: str | None = None,
    idempotency_key: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    idem = idempotency_key or (f"{case_id}|raise_reconciliation|{ref_id}" if case_id else None)
    return await call_service(
        service="refunds",
        tool_name="raise_reconciliation",
        method="POST",
        path="/reconciliations",
        acting_user=acting_user,
        json_body={"ref_type": ref_type, "ref_id": ref_id, "case_id": case_id or ""},
        idempotency_key=idem,
        case_id=case_id,
        actor=actor,
    )


async def get_reconciliation(
    *,
    acting_user: str,
    recon_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = False,
) -> ToolOutcome:
    return await call_service(
        service="refunds",
        tool_name="get_reconciliation",
        method="GET",
        path=f"/reconciliations/{recon_id}",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )
