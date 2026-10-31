"""Asynchronous T+n completion checks (F2) and RBI TAT compensation claims (F11)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.agents.runtime import compute_age_hours, format_date_short
from app.core.composer import compose_message
from app.core.config import cfg_mgr
from app.core.events import bus
from app.core.handoff import build_handoff_packet
from app.core.ids import next_id
from app.core.state_machine import transition
from app.db.core import execute, query_all, query_one, utc_now_iso
from app.mocks.common import shift_iso_ts
from app.mocks.crm.app import shift_crm_time
from app.mocks.ledger.app import shift_ledger_time
from app.mocks.notify.app import shift_notify_time
from app.mocks.refunds.app import shift_refunds_time
from app.tools import crm, notify, refunds
from app.tools.client import record_case_event


def register_followup_check(
    *,
    case_id: str,
    kind: str = "REFUND_COMPLETED",
    due_hours: float = 72.0,
    target_id: str = "",
    txn_id: str = "",
) -> int:
    due_at = (datetime.now(timezone.utc) + timedelta(hours=due_hours)).isoformat()
    fid = execute(
        """
        INSERT INTO followup_checks(case_id, kind, due_at, status, result_json, checked_at)
        VALUES (?, ?, ?, 'SCHEDULED', ?, NULL)
        """,
        (case_id, kind, due_at, json.dumps({"target_id": target_id, "txn_id": txn_id})),
    )
    record_case_event(
        case_id=case_id,
        badge="[FOLLOWUP]",
        evt_type="followup_scheduled",
        summary=f"Scheduled T+{int(due_hours)}h completion check ({kind}) for {target_id or txn_id}",
        payload={"followup_id": fid, "kind": kind, "due_at": due_at, "target_id": target_id, "txn_id": txn_id},
        status="ok",
    )
    return fid


async def check_and_record_tat_compensation(
    *,
    case_id: str,
    txn: dict[str, Any] | None,
    language: str = "en",
) -> dict[str, Any] | None:
    """
    F11: RBI TAT compensation detector for delayed failed UPI auto-reversals.
    Applies when txn.rail in applies_to_rails ([UPI]) and age_hours > tat_hours (24h).
    """
    if not txn:
        return None

    rule_cfg = (cfg_mgr.tat_rules or {}).get("upi_failed_debit", {})
    allowed_rails = rule_cfg.get("applies_to_rails", ["UPI"])
    rail = str(txn.get("rail", "BILL_PAY"))
    if rail not in allowed_rails:
        return None

    tat_hours = float(rule_cfg.get("tat_hours", 24))
    per_day = int(rule_cfg.get("per_day_compensation", 100))

    age_h = compute_age_hours(txn.get("created_at"))
    if age_h <= tat_hours:
        return None

    days_late = max(1, int(math.ceil((age_h - tat_hours) / 24.0)))
    amount_estimate = days_late * per_day
    claim_id = next_id("claim")
    ts = utc_now_iso()

    note_text, _ = await compose_message(
        "COMP_NOTE",
        {
            "tat_hours": int(tat_hours),
            "days": days_late,
            "amount": amount_estimate,
        },
        language,
        case_id=case_id,
    )

    execute(
        """
        INSERT INTO compensation_claims(id, case_id, txn_id, rule_id, days_late, amount_estimate, status, note, created_at)
        VALUES (?, ?, ?, 'upi_failed_debit', ?, ?, 'POTENTIAL', ?, ?)
        """,
        (claim_id, case_id, txn["id"], days_late, amount_estimate, note_text, ts),
    )

    claim_obj = {
        "id": claim_id,
        "case_id": case_id,
        "txn_id": txn["id"],
        "rule_id": "upi_failed_debit",
        "days_late": days_late,
        "amount_estimate": amount_estimate,
        "status": "POTENTIAL",
        "note": note_text,
        "created_at": ts,
    }
    record_case_event(
        case_id=case_id,
        badge="[POLICY]",
        evt_type="tat_compensation",
        summary=f"RBI TAT delay detected ({days_late}d past {int(tat_hours)}h window) → potential ₹{amount_estimate} claim {claim_id}",
        payload=claim_obj,
        status="warn",
    )
    return claim_obj


async def advance_time_and_run_followups(hours: float = 73.0) -> dict[str, Any]:
    """
    Shifts time across all mock services and core followup_checks, then processes due checks.
    """
    if hours > 0:
        shift_ledger_time(hours)
        shift_refunds_time(hours)
        shift_crm_time(hours)
        shift_notify_time(hours)

        rows = query_all("SELECT id, due_at FROM followup_checks WHERE status = 'SCHEDULED'")
        for r in rows:
            execute(
                "UPDATE followup_checks SET due_at = ? WHERE id = ?",
                (shift_iso_ts(r["due_at"], hours), r["id"]),
            )

    return await run_due_followups()


async def run_due_followups() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    sched_rows = query_all("SELECT * FROM followup_checks WHERE status = 'SCHEDULED' ORDER BY id ASC")

    verified_complete: list[str] = []
    reopened_cases: list[str] = []

    for row in sched_rows:
        due_str = row.get("due_at")
        if due_str:
            try:
                due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                if due_dt > now:
                    continue
            except Exception:
                pass

        chk_id = row["id"]
        case_id = row["case_id"]
        meta = json.loads(row.get("result_json") or "{}")
        refund_id = meta.get("target_id") or ""
        txn_id = meta.get("txn_id") or ""

        case_row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
        if not case_row:
            continue
        persona_id = case_row["persona_id"]
        lang = case_row.get("language") or "en"

        rf: dict[str, Any] | None = None
        if refund_id:
            r_out = await refunds.get_refund(acting_user=persona_id, refund_id=refund_id, case_id=case_id, emit_trace=False)
            if r_out.ok and isinstance(r_out.data, dict):
                rf = r_out.data
        if not rf and txn_id:
            r_out2 = await refunds.get_refund_for_txn(acting_user=persona_id, txn_id=txn_id, case_id=case_id, emit_trace=False)
            if r_out2.ok and isinstance(r_out2.data, list) and r_out2.data:
                rf = r_out2.data[0]

        if not rf:
            execute(
                "UPDATE followup_checks SET status = 'VERIFIED_COMPLETE', checked_at = ? WHERE id = ?",
                (now_iso, chk_id),
            )
            verified_complete.append(case_id)
            continue

        refund_id = rf["id"]
        txn_id = rf["txn_id"]
        amt = int(rf.get("amount", 0))

        if rf.get("status") == "COMPLETED":
            res_payload = {"refund_id": refund_id, "status": "COMPLETED", "completed_at": rf.get("completed_at") or now_iso}
            execute(
                "UPDATE followup_checks SET status = 'VERIFIED_COMPLETE', result_json = ?, checked_at = ? WHERE id = ?",
                (json.dumps(res_payload), now_iso, chk_id),
            )
            msg_text, _ = await compose_message(
                "FOLLOWUP_DONE",
                {
                    "refund_id": refund_id,
                    "amount": amt,
                    "date": format_date_short(rf.get("completed_at") or now_iso),
                },
                lang,
                case_id=case_id,
            )
            await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor="followup-monitor")
            bus.publish_customer(
                persona_id,
                "resolution",
                {
                    "case_id": case_id,
                    "text": msg_text,
                    "template_code": "FOLLOWUP_DONE",
                    "followup_status": "VERIFIED_COMPLETE",
                },
                case_id=case_id,
            )
            record_case_event(
                case_id=case_id,
                badge="[FOLLOWUP]",
                evt_type="followup_done",
                summary=f"T+72h check verified refund {refund_id} COMPLETED",
                payload=res_payload,
                status="ok",
            )
            verified_complete.append(case_id)
        else:
            # Stuck refund beyond ETA -> raise reconciliation, transition CLOSED -> REOPENED -> ESCALATED (T3)
            rc_out = await refunds.raise_reconciliation(
                acting_user=persona_id,
                ref_type="REFUND",
                ref_id=refund_id,
                case_id=case_id,
                actor="followup-monitor",
            )
            recon_id = (rc_out.data or {}).get("id", "RC-8001")
            res_payload = {
                "refund_id": refund_id,
                "status": rf.get("status"),
                "recon_id": recon_id,
                "reopened": True,
            }
            execute(
                "UPDATE followup_checks SET status = 'REOPENED', result_json = ?, checked_at = ? WHERE id = ?",
                (json.dumps(res_payload), now_iso, chk_id),
            )

            cur_state = case_row.get("state") or "CLOSED"
            if cur_state != "CLOSED":
                execute("UPDATE cases SET state = 'CLOSED' WHERE id = ?", (case_id,))
            transition(case_id, "REOPENED")
            transition(case_id, "ESCALATED")
            execute(
                "UPDATE cases SET reopened = 1, trigger = 'T3', rule_fired = 'T3', lane = 'red' WHERE id = ?",
                (case_id,),
            )

            # F7 Rule 15: Auto-tighten autonomy level by 1 step when T+n check REOPENS
            ag_name = case_row.get("agent") or "payment_failure"
            cur_modes = cfg_mgr.get_autonomy_modes()
            cur_m = cur_modes.get(ag_name, "guarded")
            drop = {"autonomous": "guarded", "guarded": "suggest", "suggest": "suggest"}.get(cur_m, "suggest")
            if drop != cur_m and ag_name not in cfg_mgr.autonomy_cfg.get("locked", ["fraud"]):
                cfg_mgr.set_autonomy_mode(ag_name, drop, actor="system")
                bus.publish_console("autonomy_updated", {"agent": ag_name, "old_mode": cur_m, "new_mode": drop, "actor": "system", "reason": f"T+n reopen on {case_id}"})
            bus.publish_console("followup_result", {"case_id": case_id, "status": "REOPENED"})

            updated_case = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) or case_row
            packet = build_handoff_packet(
                case_row=updated_case,
                diagnosis="RECON_RAISED",
                facts={"txn_id": txn_id, "refund_id": refund_id, "amount": amt, "recon_id": recon_id},
                verified_facts=[
                    f"T+72h completion check found refund {refund_id} (₹{amt}) still in {rf.get('status')} past ETA.",
                    f"Automatically raised bank reconciliation {recon_id} and reopened case.",
                ],
                actions_taken=[{"action": "raise_reconciliation", "id": recon_id}],
                rule_fired_text="Rule 2 · T3 · Follow-up SLA breach (refund stuck in PROCESSING)",
                trigger_id="T3",
            )
            await crm.post_handoff(acting_user=persona_id, case_id=case_id, packet=packet, actor="followup-monitor")

            msg_text, _ = await compose_message(
                "FOLLOWUP_DELAY",
                {
                    "refund_id": refund_id,
                    "amount": amt,
                    "eta": format_date_short(rf.get("eta")),
                    "recon_id": recon_id,
                },
                lang,
                case_id=case_id,
            )
            await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor="followup-monitor")
            bus.publish_customer(
                persona_id,
                "escalation",
                {
                    "case_id": case_id,
                    "text": msg_text,
                    "template_code": "FOLLOWUP_DELAY",
                    "followup_status": "REOPENED",
                },
                case_id=case_id,
            )
            record_case_event(
                case_id=case_id,
                badge="[FOLLOWUP]",
                evt_type="followup_reopened",
                summary=f"T+72h check found {refund_id} stuck in {rf.get('status')} → raised {recon_id} & reopened to ESCALATED",
                payload=res_payload,
                status="error",
            )
            bus.publish_console("case_updated", {"case": query_one("SELECT * FROM cases WHERE id = ?", (case_id,))})
            reopened_cases.append(case_id)

    return {
        "verified_complete": verified_complete,
        "reopened_cases": reopened_cases,
    }
