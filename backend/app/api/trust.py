"""Trust Report (/api/trust/report) and What-If Simulator (/api/trust/whatif) API Routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.eval.harness import build_trust_report, compute_whatif

router = APIRouter(prefix="/api/trust", tags=["trust"])


@router.get("/report")
async def get_trust_report_route():
    return build_trust_report()


@router.post("/whatif")
async def post_trust_whatif_route(payload: dict[str, Any] | None = None):
    body = payload or {}
    autonomy_override = body.get("autonomy") or body.get("modes")
    proposed_cap = body.get("proposed_cap_inr")
    if proposed_cap is not None:
        proposed_cap = int(proposed_cap)
    return compute_whatif(autonomy_override=autonomy_override, proposed_cap_inr=proposed_cap)

