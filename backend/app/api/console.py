"""Console, Command Center, Approvals, Autonomy, Kill-Switch, Systems, and Incident API Routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.auth import get_console_persona, get_ops_lead_persona
from app.core.config import cfg_mgr
from app.core.events import bus
from app.core.handoff import build_why_you_line
from app.core.incidents import preview_incident, publish_incident_notice, resolve_incident
from app.core.orchestrator import (
    add_case_note,
    decide_approval,
    get_case_detail,
    handback_case_to_ai,
    human_reply_to_case,
    mark_case_wrong,
    record_decision_view,
    release_case_ownership,
    take_case_ownership,
)
from app.db.core import query_all, query_one
from app.mocks.crm.app import crm_sim, get_crm_rows
from app.mocks.crm.db import crm_db
from app.mocks.ledger.app import get_ledger_rows, ledger_sim
from app.mocks.ledger.db import ledger_db
from app.mocks.notify.app import get_notify_rows, notify_sim
from app.mocks.notify.db import notify_db
from app.mocks.refunds.app import get_refunds_rows, refunds_sim
from app.mocks.refunds.db import refunds_db

router = APIRouter(prefix="/api/console", tags=["console"])


@router.get("/cases")
async def list_cases(
    lane: str | None = Query(default=None),
    state: str | None = Query(default=None),
    agent: str | None = Query(default=None),
    persona: dict[str, Any] = Depends(get_console_persona),
):
    sql = "SELECT * FROM cases WHERE 1=1"
    params: list[Any] = []
    if lane:
        sql += " AND lane = ?"
        params.append(lane)
    if state:
        sql += " AND state = ?"
        params.append(state)
    if agent:
        sql += " AND agent = ?"
        params.append(agent)
    sql += " ORDER BY created_at DESC LIMIT 100"
    rows = query_all(sql, params)
    personas_map = cfg_mgr.get_personas()
    out = []
    for r in rows:
        item = dict(r)
        p_info = personas_map.get(r["persona_id"], {})
        item["customer_name"] = p_info.get("name", r["persona_id"])
        item["customer_role"] = p_info.get("role", "consumer")
        out.append(item)
    return {"cases": out}


@router.get("/cases/{case_id}")
async def get_console_case(
    case_id: str,
    persona: dict[str, Any] = Depends(get_console_persona),
):
    try:
        return await get_case_detail(case_id)
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "not_found"})


@router.post("/cases/{case_id}/take-ownership")
async def post_take_ownership(
    case_id: str,
    payload: dict[str, Any] | None = None,
    persona: dict[str, Any] = Depends(get_console_persona),
):
    actor = (payload or {}).get("actor") or persona["id"]
    return await take_case_ownership(case_id, actor=str(actor))


@router.post("/cases/{case_id}/release-ownership")
async def post_release_ownership(
    case_id: str,
    payload: dict[str, Any] | None = None,
    persona: dict[str, Any] = Depends(get_console_persona),
):
    actor = (payload or {}).get("actor") or persona["id"]
    return await release_case_ownership(case_id, actor=str(actor))


@router.post("/cases/{case_id}/reply")
async def post_human_reply(
    case_id: str,
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail={"error": "empty_reply"})
    actor = payload.get("actor") or persona["id"]
    return await human_reply_to_case(case_id, text=text, actor=str(actor))


@router.post("/cases/{case_id}/note")
async def post_case_note(
    case_id: str,
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail={"error": "empty_note"})
    author = payload.get("author") or persona["id"]
    return await add_case_note(case_id, text=text, author=str(author))


@router.post("/cases/{case_id}/handback")
async def post_case_handback(
    case_id: str,
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    instruction = str(payload.get("instruction") or "RECHECK").upper()
    actor = payload.get("actor") or persona["id"]
    try:
        return await handback_case_to_ai(case_id, instruction=instruction, actor=str(actor))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.post("/cases/{case_id}/mark-wrong")
async def post_case_mark_wrong(
    case_id: str,
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    reason_code = str(payload.get("reason_code") or "WRONG_AUTO_DECISION")
    suggested_change = str(payload.get("suggested_change") or "Require human approval for this pattern")
    actor = payload.get("actor") or persona["id"]
    try:
        return await mark_case_wrong(
            case_id,
            reason_code=reason_code,
            suggested_change=suggested_change,
            actor=str(actor),
        )
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@router.get("/approvals")
async def list_approvals(
    status: str | None = Query(default=None),
    persona: dict[str, Any] = Depends(get_console_persona),
):
    sql = "SELECT * FROM approvals"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = query_all(sql, params)
    personas_map = cfg_mgr.get_personas()
    pol_cfg = cfg_mgr.get_policy_config()

    out = []
    for r in rows:
        prop = json.loads(r.get("proposed_action_json") or "{}")
        case_row = query_one("SELECT * FROM cases WHERE id = ?", (r["case_id"],)) or {}
        conf_row = query_one("SELECT * FROM confidence_log WHERE case_id = ?", (r["case_id"],))
        conf_signals = json.loads(conf_row["signals_json"]) if conf_row and conf_row.get("signals_json") else {}
        agent_name = case_row.get("agent") or "payment_failure"
        mode = pol_cfg.autonomy.get(agent_name, "guarded")
        cap = pol_cfg.modes.get(mode, {"auto_cap": 5000})["auto_cap"]
        amt = int((prop.get("args") or {}).get("amount") or (prop.get("facts") or {}).get("amount") or 0)
        why_you = build_why_you_line(
            rule=r.get("rule_fired") or "4",
            agent_name=agent_name,
            amount=amt,
            cap=cap,
            confidence_score=case_row.get("confidence"),
            min_conf=pol_cfg.min_auto_confidence,
        )
        p_info = personas_map.get(case_row.get("persona_id", ""), {})
        out.append(
            {
                **r,
                "proposed_action": prop,
                "case": case_row,
                "customer_name": p_info.get("name", case_row.get("persona_id")),
                "why_you": why_you,
                "confidence": {
                    "score": case_row.get("confidence", 0.85),
                    "band": case_row.get("confidence_band", "high"),
                    **conf_signals,
                },
            }
        )
    return {"approvals": out}


@router.post("/approvals/{approval_id}/decide")
async def post_decide_approval(
    approval_id: str,
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    decision = str(payload.get("decision") or "APPROVED").upper()
    if decision not in ("APPROVED", "EDITED", "REJECTED"):
        return JSONResponse(status_code=400, content={"error": "invalid_decision"})
    actor = payload.get("actor") or persona["id"]
    edited_reply = payload.get("edited_reply")
    reason_code = payload.get("reason_code")
    reason_text = payload.get("reason_text")
    view_mode = str(payload.get("view_mode") or "card")
    try:
        return await decide_approval(
            approval_id,
            decision=decision,
            actor=str(actor),
            edited_reply=edited_reply,
            reason_code=reason_code,
            reason_text=reason_text,
            view_mode=view_mode,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.post("/decision-view")
async def post_decision_view(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    approval_id = str(payload.get("approval_id") or "")
    view_mode = str(payload.get("view_mode") or "card")
    if not approval_id:
        return JSONResponse(status_code=400, content={"error": "missing_approval_id"})
    return record_decision_view(approval_id, view_mode=view_mode, actor=persona["id"])


@router.get("/autonomy")
async def get_autonomy_state(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    pol_cfg = cfg_mgr.get_policy_config()
    audit = query_all("SELECT * FROM config_audit ORDER BY id DESC LIMIT 30")
    return {
        "modes": pol_cfg.autonomy,
        "mode_definitions": pol_cfg.modes,
        "locked": pol_cfg.locked,
        "ceiling": pol_cfg.ceiling,
        "min_auto_confidence": pol_cfg.min_auto_confidence,
        "velocity_max_auto_refunds_24h": pol_cfg.velocity_max_auto_refunds_24h,
        "velocity_max_auto_amount_24h": pol_cfg.velocity_max_auto_amount_24h,
        "killswitches": cfg_mgr.get_killswitches(),
        "audit": audit,
    }


@router.put("/autonomy")
async def put_autonomy_mode(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    agent = str(payload.get("agent") or "")
    mode = str(payload.get("mode") or "")
    try:
        old_mode = cfg_mgr.set_autonomy_mode(agent, mode, actor=persona["id"])
        bus.publish_console("autonomy_updated", {"agent": agent, "old_mode": old_mode, "new_mode": mode, "actor": persona["id"]})
        return {"ok": True, "agent": agent, "old_mode": old_mode, "new_mode": mode, "modes": cfg_mgr.get_autonomy_modes()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/autonomy-evidence")
async def get_autonomy_evidence_route(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    modes = cfg_mgr.get_autonomy_modes()
    locked = set(cfg_mgr.autonomy_cfg.get("locked", ["fraud"]))
    agents_list = ["payment_failure", "refund", "settlement", "app_assistance", "fraud"]
    evidence: dict[str, Any] = {}
    for ag in agents_list:
        rows = query_all("SELECT agreed, source FROM autonomy_decisions WHERE agent = ?", (ag,))
        tot = len(rows)
        agr = sum(1 for r in rows if int(r.get("agreed") or 0) == 1)
        reops = query_all("SELECT id FROM cases WHERE agent = ? AND reopened = 1", (ag,))
        wrongs = query_all("SELECT id FROM override_tests WHERE snapshot_json LIKE ?", (f'%"{ag}"%',))
        cur_m = modes.get(ag, "guarded")
        next_m = {"suggest": "guarded", "guarded": "autonomous", "autonomous": None}.get(cur_m)
        can_promote = (
            ag not in locked
            and next_m is not None
            and len(reops) == 0
            and len(wrongs) == 0
        )
        evidence[ag] = {
            "agent": ag,
            "current_mode": cur_m,
            "next_mode": next_m,
            "locked": ag in locked,
            "decisions_total": tot,
            "decisions_agreed": agr,
            "agreement_rate": round(agr / tot, 4) if tot > 0 else 1.0,
            "reopened_count": len(reops),
            "marked_wrong_count": len(wrongs),
            "can_promote": can_promote,
            "evidence_line": f"{agr}/{tot} shadow/live decisions agreed · {len(reops)} reopens · {len(wrongs)} overrides",
        }
    return {"evidence": evidence, "modes": modes}


@router.post("/autonomy/promote")
async def post_promote_autonomy(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    agent = str(payload.get("agent") or "payment_failure")
    locked = set(cfg_mgr.autonomy_cfg.get("locked", ["fraud"]))
    if agent in locked:
        return JSONResponse(status_code=400, content={"error": "agent_locked"})
    modes = cfg_mgr.get_autonomy_modes()
    cur_m = modes.get(agent, "guarded")
    next_m = payload.get("target_mode") or {"suggest": "guarded", "guarded": "autonomous", "autonomous": "autonomous"}.get(cur_m, "guarded")
    try:
        old_m = cfg_mgr.set_autonomy_mode(agent, str(next_m), actor=persona["id"])
        bus.publish_console("autonomy_updated", {"agent": agent, "old_mode": old_m, "new_mode": next_m, "actor": persona["id"]})
        return {"ok": True, "agent": agent, "old_mode": old_m, "new_mode": next_m, "modes": cfg_mgr.get_autonomy_modes()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/killswitch")
async def get_killswitch_route(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    return {"killswitches": cfg_mgr.get_killswitches()}


@router.put("/killswitch")
async def put_killswitch_route(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_console_persona),
):
    scope = str(payload.get("scope") or "all")
    paused = bool(payload.get("paused", False))
    # SPEC_V6 §9 & §12.9: Any console user can pause, but resuming (paused=False) requires ops_lead
    if not paused and persona.get("role") != "ops_lead":
        return JSONResponse(status_code=403, content={"error": "ops_lead_required_to_resume"})
    try:
        cfg_mgr.set_killswitch(scope, paused, actor=persona["id"])
        bus.publish_console("kill_switch_changed", {"scope": scope, "paused": paused, "actor": persona["id"]})
        return {"ok": True, "scope": scope, "paused": paused, "killswitches": cfg_mgr.get_killswitches()}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@router.get("/lanes")
async def get_lanes_counts(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    rows = query_all("SELECT lane, state, outcome, reopened FROM cases")
    counts = {
        "green": {"total": 0, "open": 0, "closed": 0, "label": "GREEN · Auto-Safe"},
        "amber": {"total": 0, "open": 0, "closed": 0, "label": "AMBER · Guarded / Approval"},
        "red": {"total": 0, "open": 0, "closed": 0, "label": "RED · Critical / Human Required"},
    }
    for r in rows:
        ln = r.get("lane") if r.get("lane") in counts else "amber"
        counts[ln]["total"] += 1
        if r.get("state") == "CLOSED":
            counts[ln]["closed"] += 1
        else:
            counts[ln]["open"] += 1
    pending_approvals = int((query_one("SELECT COUNT(*) AS c FROM approvals WHERE status = 'PENDING'") or {}).get("c", 0))
    escalated_open = int((query_one("SELECT COUNT(*) AS c FROM cases WHERE state = 'ESCALATED'") or {}).get("c", 0))
    reopened_total = int((query_one("SELECT COUNT(*) AS c FROM cases WHERE reopened = 1") or {}).get("c", 0))
    return {
        "lanes": counts,
        "pending_approvals": pending_approvals,
        "escalated_open": escalated_open,
        "reopened_total": reopened_total,
        "total_cases": len(rows),
    }


@router.get("/overrides")
async def get_overrides_route(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    rows = query_all("SELECT * FROM override_tests ORDER BY id DESC LIMIT 50")
    out = []
    for r in rows:
        out.append({**r, "snapshot": json.loads(r.get("snapshot_json") or "{}")})
    return {"overrides": out}


@router.get("/systems")
async def get_systems_status(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    services_data = {}
    for name, db_inst, sim_inst, rows_fn in (
        ("ledger", ledger_db, ledger_sim, get_ledger_rows),
        ("refunds", refunds_db, refunds_sim, get_refunds_rows),
        ("crm", crm_db, crm_sim, get_crm_rows),
        ("notify", notify_db, notify_sim, get_notify_rows),
    ):
        pending = sim_inst.pending_failures_count()
        phantoms = sim_inst.pending_phantoms_count()
        last_reqs = db_inst.query_all(
            "SELECT id, ts, method, path, acting_user, actor, status, latency_ms, case_hint FROM request_log ORDER BY id DESC LIMIT 8"
        )
        services_data[name] = {
            "service": name,
            "health": "degraded" if (pending > 0 or phantoms > 0) else "healthy",
            "pending_failures": pending,
            "pending_phantoms": phantoms,
            "stuck_txns": list(sim_inst.stuck_txn_ids),
            "latency_min_ms": sim_inst.latency_min_ms,
            "latency_max_ms": sim_inst.latency_max_ms,
            "last_requests": last_reqs,
            "last_request": last_reqs[0] if last_reqs else None,
            "rows": rows_fn(8),
        }
    return {"systems": services_data}


@router.get("/incidents")
async def list_incidents_route(
    persona: dict[str, Any] = Depends(get_console_persona),
):
    rows = query_all("SELECT * FROM incidents ORDER BY detected_at DESC")
    return {"incidents": rows}


@router.get("/incidents/{incident_id}")
async def get_incident_detail_route(
    incident_id: str,
    persona: dict[str, Any] = Depends(get_console_persona),
):
    inc = query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not inc:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    actions = query_all("SELECT * FROM incident_actions WHERE incident_id = ? ORDER BY id ASC", (incident_id,))
    signals = query_all("SELECT * FROM complaint_signals WHERE signature = ? ORDER BY id DESC LIMIT 30", (inc["signature"],))
    return {"incident": inc, "actions": actions, "signals": signals}


@router.post("/incidents/{incident_id}/preview")
async def post_incident_preview_route(
    incident_id: str,
    persona: dict[str, Any] = Depends(get_console_persona),
):
    try:
        return await preview_incident(incident_id, actor=f"human:{persona['id']}")
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@router.post("/incidents/{incident_id}/publish-notice")
async def post_incident_publish_notice_route(
    incident_id: str,
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    try:
        inc = await publish_incident_notice(incident_id, actor=persona["id"])
        return {"ok": True, "incident": inc}
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@router.post("/incidents/{incident_id}/resolve")
async def post_incident_resolve_route(
    incident_id: str,
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    try:
        return await resolve_incident(incident_id, actor=persona["id"])
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})

