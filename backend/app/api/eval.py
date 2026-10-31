"""Evaluation Runner API Routes (/api/eval/run, /api/eval/runs, /api/eval/runs/{id})."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.auth import get_console_persona, get_ops_lead_persona
from app.db.core import query_all, query_one
from app.eval.harness import reset_all_data, run_all_trust_suites, run_suite, set_eval_sim_latency

router = APIRouter(prefix="/api/eval", tags=["eval"])


@router.post("/run")
async def post_eval_run(
    payload: dict[str, Any] | None = None,
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    body = payload or {}
    suite_or_kind = str(body.get("suite") or body.get("kind") or "core")
    split = str(body.get("split") or "all")
    k = int(body.get("k") or 5)
    ablate = body.get("ablate")
    arm = str(body.get("arm") or "C")

    if suite_or_kind == "trust_all":
        rep = await run_all_trust_suites()
        return {"ok": True, "trust_report": rep}

    res = await run_suite(
        kind=suite_or_kind,
        split=split,
        k=k,
        ablate=ablate,
        arm=arm,
    )
    reset_all_data(preserve_eval_runs=True, preserve_confidence_log=True)
    set_eval_sim_latency(fast=False)
    return res


@router.get("/runs")
async def get_eval_runs(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    rows = query_all("SELECT id, ts, split, status, progress FROM eval_runs ORDER BY ts DESC LIMIT 50")
    return {"runs": rows}


@router.get("/runs/{run_id}")
async def get_eval_run_detail(
    run_id: str,
    persona: dict[str, Any] = Depends(get_console_persona),
):
    row = query_one("SELECT * FROM eval_runs WHERE id = ?", (run_id,))
    if not row:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    try:
        res = json.loads(row["results_json"])
    except Exception:
        res = {}
    return {
        "id": row["id"],
        "ts": row["ts"],
        "split": row["split"],
        "status": row["status"],
        "progress": row["progress"],
        "results": res,
    }

