"""Ops-scoped cross-account query tool (F3 incident containment)."""
from __future__ import annotations

from app.tools.client import ToolOutcome, call_service


async def ops_list_affected(
    *,
    acting_user: str = "OPS",
    actor: str = "incident-monitor",
    bank_code: str | None = None,
    since_hours: float = 48.0,
    case_id: str | None = None,
) -> ToolOutcome:
    params: dict[str, object] = {"since_hours": since_hours}
    if bank_code:
        params["bank_code"] = bank_code
    return await call_service(
        service="ledger",
        tool_name="ops_list_affected",
        method="GET",
        path="/ops/affected",
        acting_user=acting_user,
        actor=actor,
        params=params,
        case_id=case_id,
        emit_trace=False,
    )
