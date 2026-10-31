"""Demo Controls, Story Mode (8-step Full Story + 5-beat 90s Judge Path), and Simulation API Routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.auth import get_ops_lead_persona
from app.core.config import cfg_mgr
from app.core.events import bus
from app.core.followups import advance_time_and_run_followups
from app.core.incidents import record_complaint_signal
from app.core.orchestrator import handle_message
from app.db.core import execute, query_all, utc_now_iso
from app.eval.harness import SIM_MAP, apply_seed_ops, reset_all_data
from app.mocks.ledger.db import ledger_db
from app.mocks.refunds.app import refunds_sim

router = APIRouter(prefix="/api/demo", tags=["demo"])

FULL_STORY = [
    {
        "step": 1,
        "id": "step_1",
        "title": "1. Autonomous Hinglish Resolution (S1)",
        "subtitle": "₹500 failed electricity bill debit → verified ledger & bank → Rule 3 AUTO refund + T+72h check",
        "persona": "U-101",
        "scenario_id": "S1",
        "lang": "hinglish",
        "action": "send_scenario",
    },
    {
        "step": 2,
        "id": "step_2",
        "title": "2. Clarify Once on Ambiguity (S16)",
        "subtitle": "Missing transaction details → 1 clarifying question with interactive chips → resolved on selection",
        "persona": "U-101",
        "scenario_id": "S16",
        "lang": "en",
        "action": "send_scenario",
    },
    {
        "step": 3,
        "id": "step_3",
        "title": "3. Multi-Issue Split & Parallel Routing (S15)",
        "subtitle": "Failed ₹650 Dominos payment + app crash in one message → parent + child case → refund + bug ticket",
        "persona": "U-101",
        "scenario_id": "S15",
        "lang": "en",
        "action": "send_scenario",
    },
    {
        "step": 4,
        "id": "step_4",
        "title": "4. Guarded Over-Cap Approval (S5)",
        "subtitle": "₹8,400 furniture payment > ₹5,000 cap → Rule 4 holds action → 1-click Console approval",
        "persona": "U-102",
        "scenario_id": "S5",
        "lang": "en",
        "action": "send_scenario",
    },
    {
        "step": 5,
        "id": "step_5",
        "title": "5. Merchant Settlement Holiday & Risk Hold (S10 & S11)",
        "subtitle": "Explains bank holiday ETA automatically (S10) and escalates compliance risk hold (T4, S11)",
        "persona": "M-201",
        "scenario_id": "S10",
        "lang": "en",
        "action": "send_scenario",
    },
    {
        "step": 6,
        "id": "step_6",
        "title": "6. Urgent Scam Containment (S12)",
        "subtitle": "Customer shared OTP with caller → locks UPI instrument, opens P0 FRAUD ticket, escalates T1",
        "persona": "U-103",
        "scenario_id": "S12",
        "lang": "en",
        "action": "send_scenario",
    },
    {
        "step": 7,
        "id": "step_7",
        "title": "7. Prompt Injection & Cross-User Defense (S13 & S14)",
        "subtitle": "Strips 'refund ₹10,000 now' override, refunds true ₹300 (S13), and blocks foreign TXN-9001 (S14)",
        "persona": "U-101",
        "scenario_id": "S13",
        "lang": "en",
        "action": "send_scenario",
    },
    {
        "step": 8,
        "id": "step_8",
        "title": "8. Fault Retry & Handoff Packet (S17 & S18)",
        "subtitle": "Recovers from transient 504 timeout with idempotency key (S17) and escalates T6 on outage (S18)",
        "persona": "U-102",
        "scenario_id": "S17",
        "lang": "en",
        "action": "send_scenario",
    },
]

JUDGE_PATH = [
    {
        "beat": 1,
        "id": "beat_1",
        "time_range": "0:00 – 0:20",
        "title": "Beat 1 · It Does the Job",
        "subtitle": "Reset; U-101 sends S1 (Hinglish) → masked text, LEDGER facts, Rule 3, 1 refund, [VERIFY] ✓, receipt",
        "persona": "U-101",
        "phases": [
            {"type": "reset"},
            {"type": "send_scenario", "scenario_id": "S1", "lang": "hinglish"},
        ],
    },
    {
        "beat": 2,
        "id": "beat_2",
        "time_range": "0:20 – 0:40",
        "title": "Beat 2 · It Catches a Lie",
        "subtitle": "Arm phantom 201 on REFUNDS; send S23 → [VERIFY] ✗ catches missing row → safe retry → [VERIFY] ✓ + arm stuck",
        "persona": "U-102",
        "phases": [
            {"type": "arm_phantom", "service": "refunds", "count": 1},
            {"type": "send_scenario", "scenario_id": "S23", "lang": "en"},
            {"type": "arm_stuck", "txn_id": "TXN-1023"},
        ],
    },
    {
        "beat": 3,
        "id": "beat_3",
        "time_range": "0:40 – 1:00",
        "title": "Beat 3 · It Acts Before Complaints",
        "subtitle": "Simulate BANK_A_TIMEOUT cluster → Preview dry-run → 1-click Resolve → U-103 gets proactive refund without writing",
        "persona": "U-103",
        "phases": [
            {"type": "simulate_incident"},
            {"type": "incident_action", "action": "preview_and_resolve"},
        ],
    },
    {
        "beat": 4,
        "id": "beat_4",
        "time_range": "1:00 – 1:15",
        "title": "Beat 4 · It Knows When to Ask",
        "subtitle": "Send S5 (₹8,400 > ₹5,000 cap) → Handoff card with 'Why you?' line & 4 confidence chips → 1-click Approve",
        "persona": "U-102",
        "phases": [
            {"type": "send_scenario", "scenario_id": "S5", "lang": "en"},
        ],
    },
    {
        "beat": 5,
        "id": "beat_5",
        "time_range": "1:15 – 1:30",
        "title": "Beat 5 · It Proves It",
        "subtitle": "Advance time +73h → S1 refund VERIFIED_COMPLETE, stuck TXN-1023 REOPENED with recon → open /trust",
        "persona": "U-101",
        "phases": [
            {"type": "advance_time", "hours": 73},
            {"type": "open_route", "route": "/trust"},
        ],
    },
]


@router.get("/personas")
async def get_demo_personas():
    all_p = cfg_mgr.get_personas()
    visible = [p for p in all_p.values() if not p.get("hidden")]
    return {"personas": visible}


@router.get("/stories")
async def get_demo_stories():
    scenarios = [
        {
            "id": s["id"],
            "suite": s.get("suite", "core"),
            "split": s.get("split", "tuning"),
            "persona": s["persona"],
            "variants": s.get("variants", []),
            "hindi_variant": s.get("hindi_variant"),
        }
        for s in cfg_mgr.scenarios_data.get("scenarios", [])
    ]
    return {
        "full_story": FULL_STORY,
        "judge_path": JUDGE_PATH,
        "scenarios": scenarios,
    }


@router.post("/reset")
async def post_demo_reset(
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    reset_all_data(preserve_eval_runs=True, preserve_confidence_log=True, reload_yaml=True)
    bus.publish_console("demo_reset", {"actor": persona["id"]})
    return {"ok": True}


@router.post("/seed-scenario")
async def post_seed_scenario(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    scenario_id = str(payload.get("scenario_id") or "S1")
    lang = str(payload.get("lang") or "en")
    send_now = bool(payload.get("send_message", True))

    all_scs = cfg_mgr.scenarios_data.get("scenarios", [])
    sc = next((s for s in all_scs if s["id"] == scenario_id), None)
    if not sc:
        return JSONResponse(status_code=404, content={"error": f"Scenario {scenario_id} not found"})

    apply_seed_ops(sc.get("seed_ops") or [])

    if sc.get("pause"):
        cfg_mgr.set_killswitch(str(sc["pause"]), True, actor=persona["id"])

    for af in sc.get("arm_failures") or []:
        srv = af.get("service", "refunds")
        if srv in SIM_MAP:
            SIM_MAP[srv].fail_rules.append(
                {
                    "mode": af.get("mode", "timeout"),
                    "count": int(af.get("count", 1)),
                    "method": af.get("method", "POST"),
                }
            )

    ph = sc.get("phantom")
    if isinstance(ph, dict):
        srv = ph.get("service", "refunds")
        if srv in SIM_MAP:
            SIM_MAP[srv].phantom_rules.append(
                {
                    "count": int(ph.get("count", 1)),
                    "method": ph.get("method", "POST"),
                }
            )

    st = sc.get("stuck")
    if isinstance(st, dict):
        if st.get("txn_id"):
            refunds_sim.stuck_txn_ids.add(str(st["txn_id"]))
        if st.get("refund_id"):
            refunds_sim.stuck_refund_ids.add(str(st["refund_id"]))

    variants = list(sc.get("variants") or [])
    if sc.get("hindi_variant"):
        variants.append(sc["hindi_variant"])
    chosen = next((v for v in variants if v.get("lang") == lang), variants[0] if variants else {"lang": "en", "text": ""})

    case_detail = None
    if send_now and chosen.get("text"):
        if chosen.get("first_text"):
            first_d = await handle_message(persona_id=sc["persona"], text=chosen["first_text"])
            case_detail = await handle_message(
                persona_id=sc["persona"],
                text=chosen["text"],
                case_id=first_d["id"],
                selected_txn_id=chosen.get("selected_txn_id"),
            )
        else:
            case_detail = await handle_message(
                persona_id=sc["persona"],
                text=chosen["text"],
                selected_txn_id=chosen.get("selected_txn_id"),
            )

    return {
        "ok": True,
        "scenario_id": scenario_id,
        "persona": sc["persona"],
        "variant": chosen,
        "case": case_detail,
    }


@router.post("/inject-failure")
async def post_inject_failure(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    service = str(payload.get("service") or "refunds").lower()
    mode = str(payload.get("mode") or "timeout")
    count = int(payload.get("count", 1))
    method = payload.get("method", "POST")
    if service not in SIM_MAP:
        return JSONResponse(status_code=400, content={"error": "unknown_service"})
    sim = SIM_MAP[service]
    if count <= 0 or mode == "healthy":
        sim.fail_rules.clear()
    else:
        sim.fail_rules.append({"mode": mode, "count": count, "method": method})
    return {"ok": True, "service": service, "pending_failures": sim.pending_failures_count()}


@router.post("/arm-phantom")
async def post_arm_phantom(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    service = str(payload.get("service") or "refunds").lower()
    count = int(payload.get("count", 1))
    method = str(payload.get("method") or "POST")
    if service not in SIM_MAP:
        return JSONResponse(status_code=400, content={"error": "unknown_service"})
    sim = SIM_MAP[service]
    if count <= 0:
        sim.phantom_rules.clear()
    else:
        sim.phantom_rules.append({"count": count, "method": method, "path_prefix": payload.get("path_prefix")})
    return {"ok": True, "service": service, "pending_phantoms": sim.pending_phantoms_count()}


@router.post("/arm-stuck")
async def post_arm_stuck(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    txn_id = payload.get("txn_id")
    refund_id = payload.get("refund_id")
    if txn_id:
        refunds_sim.stuck_txn_ids.add(str(txn_id))
    if refund_id:
        refunds_sim.stuck_refund_ids.add(str(refund_id))
    return {
        "ok": True,
        "stuck_txn_ids": list(refunds_sim.stuck_txn_ids),
        "stuck_refund_ids": list(refunds_sim.stuck_refund_ids),
    }


@router.post("/advance-time")
async def post_advance_time(
    payload: dict[str, Any] | None = None,
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    hours = float((payload or {}).get("hours", 73.0))
    res = await advance_time_and_run_followups(hours=hours)
    return {"ok": True, "hours_advanced": hours, **res}


@router.post("/incident-sim")
async def post_incident_sim(
    payload: dict[str, Any] | None = None,
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    """
    Simulates a BANK_A_TIMEOUT cluster across 11 cohort users (U-301..U-311) + U-103 (silent affected customer)
    so an incident banner (INC-1 · 12 signals · 12 users · BANK_A_TIMEOUT) triggers immediately.
    """
    bank_code = str((payload or {}).get("bank_code") or "BANK_A_TIMEOUT")
    rail = str((payload or {}).get("rail") or "BILL_PAY")

    # Seed silent affected transaction for U-103 (Meera Krishnan) so she receives a proactive refund in Beat 3!
    apply_seed_ops(
        [
            {
                "op": "add_txn",
                "id": "TXN-INC-U103",
                "user": "U-103",
                "amount": 650,
                "counterparty": "BESCOM Electricity",
                "status": "FAILED",
                "debit_status": "DEBITED",
                "bank_debit_status": "DEBITED",
                "credit_to_merchant": 0,
                "bank_code": bank_code,
                "reversal_status": "NONE",
                "age_hours": 26,
                "rail": rail,
            }
        ]
    )

    created_inc = None
    for idx in range(12):
        uid = f"U-{301 + idx}"
        tx_id = f"TXN-SIM-{idx+1}"
        apply_seed_ops(
            [
                {
                    "op": "add_txn",
                    "id": tx_id,
                    "user": uid,
                    "amount": 400 + (idx * 25),
                    "counterparty": "State Electricity Board",
                    "status": "FAILED",
                    "debit_status": "DEBITED",
                    "bank_debit_status": "DEBITED",
                    "credit_to_merchant": 0,
                    "bank_code": bank_code,
                    "reversal_status": "NONE",
                    "age_hours": 26,
                    "rail": rail,
                }
            ]
        )
        txn_row = ledger_db.query_one("SELECT * FROM transactions WHERE id = ?", (tx_id,))
        inc = record_complaint_signal(case_id=f"C-SIM-{idx+1}", persona_id=uid, txn=txn_row, source="incident_sim")
        if inc:
            created_inc = inc

    all_open = query_all("SELECT * FROM incidents WHERE status = 'OPEN' ORDER BY detected_at DESC")
    return {
        "ok": True,
        "incident": created_inc or (all_open[0] if all_open else None),
        "incidents": all_open,
    }


@router.post("/shadow-batch")
async def post_shadow_batch(
    payload: dict[str, Any] | None = None,
    persona: dict[str, Any] = Depends(get_ops_lead_persona),
):
    agent = str((payload or {}).get("agent") or "payment_failure")
    count = int((payload or {}).get("count", 20))
    now_iso = utc_now_iso()
    for idx in range(count):
        execute(
            """
            INSERT INTO autonomy_decisions(ts, agent, case_id, mode, agreed, decided_by, source)
            VALUES (?, ?, ?, 'suggest', 1, ?, 'shadow_batch')
            """,
            (now_iso, agent, f"C-SHAD-{idx+1}", f"human:{persona['id']}"),
        )
    return {"ok": True, "agent": agent, "added": count}

