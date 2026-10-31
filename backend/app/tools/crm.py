"""CRM tool wrappers matching app/mocks/crm/app.py."""
from __future__ import annotations

from typing import Any

from app.tools.client import ToolOutcome, call_service


async def get_customer_profile(
    *,
    acting_user: str,
    customer_id: str | None = None,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = False,
) -> ToolOutcome:
    cid = customer_id or acting_user
    return await call_service(
        service="crm",
        tool_name="get_customer_profile",
        method="GET",
        path=f"/customers/{cid}",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )


async def sync_crm_case(
    *,
    acting_user: str,
    case_id: str,
    agent: str,
    state: str,
    owner_id: str = "",
    outcome: str = "",
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="crm",
        tool_name="sync_crm_case",
        method="PATCH",
        path=f"/cases/{case_id}",
        acting_user=acting_user,
        json_body={"agent": agent, "state": state, "owner_id": owner_id, "outcome": outcome},
        case_id=case_id,
        actor=actor,
        emit_trace=False,
    )


async def create_ticket(
    *,
    acting_user: str,
    case_id: str,
    category: str,
    details: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="crm",
        tool_name="create_ticket",
        method="POST",
        path="/tickets",
        acting_user=acting_user,
        json_body={"case_id": case_id, "category": category, "details": details or {}},
        idempotency_key=idempotency_key or f"{case_id}|create_ticket|{category}",
        case_id=case_id,
        actor=actor,
    )


async def get_ticket(
    *,
    acting_user: str,
    ticket_id: str,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = False,
) -> ToolOutcome:
    return await call_service(
        service="crm",
        tool_name="get_ticket",
        method="GET",
        path=f"/tickets/{ticket_id}",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )


async def post_handoff(
    *,
    acting_user: str,
    case_id: str,
    packet: dict[str, Any],
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="crm",
        tool_name="post_handoff",
        method="POST",
        path="/handoffs",
        acting_user=acting_user,
        json_body={"case_id": case_id, "packet": packet},
        case_id=case_id,
        actor=actor,
    )


async def add_crm_note(
    *,
    acting_user: str,
    case_id: str,
    author: str,
    text: str,
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="crm",
        tool_name="add_crm_note",
        method="POST",
        path="/notes",
        acting_user=acting_user,
        json_body={"case_id": case_id, "author": author, "text": text},
        case_id=case_id,
        actor=actor,
        emit_trace=False,
    )
