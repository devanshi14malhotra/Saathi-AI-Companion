"""Notifications tool wrappers matching app/mocks/notify/app.py."""
from __future__ import annotations

from app.tools.client import ToolOutcome, call_service


async def send_message(
    *,
    acting_user: str,
    message: str,
    channel: str = "in_app",
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = False,
) -> ToolOutcome:
    return await call_service(
        service="notify",
        tool_name="send_message",
        method="POST",
        path="/messages",
        acting_user=acting_user,
        json_body={"channel": channel, "message": message, "case_id": case_id or ""},
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )


async def schedule_followup(
    *,
    acting_user: str,
    case_id: str,
    run_in_minutes: int = 360,
    check_kind: str = "REFUND_COMPLETED",
    actor: str = "saathi",
) -> ToolOutcome:
    return await call_service(
        service="notify",
        tool_name="schedule_followup",
        method="POST",
        path="/followups",
        acting_user=acting_user,
        json_body={"case_id": case_id, "run_in_minutes": run_in_minutes, "check": check_kind},
        case_id=case_id,
        actor=actor,
    )


async def get_outbox(
    *,
    acting_user: str,
    case_id: str | None = None,
    actor: str = "saathi",
    emit_trace: bool = False,
) -> ToolOutcome:
    return await call_service(
        service="notify",
        tool_name="get_outbox",
        method="GET",
        path="/outbox",
        acting_user=acting_user,
        case_id=case_id,
        actor=actor,
        emit_trace=emit_trace,
    )
