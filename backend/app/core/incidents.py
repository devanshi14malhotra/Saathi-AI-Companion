"""Incident monitor and proactive resolution (F3 in SPEC_V6 §6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.composer import compose_message, get_template_text
from app.core.config import cfg_mgr
from app.core.events import bus
from app.core.followups import check_and_record_tat_compensation, register_followup_check
from app.core.ids import next_id
from app.core.policy import CasePolicyContext, ProposedAction, evaluate as evaluate_policy
from app.core.verify import verify_and_recover
from app.db.core import execute, query_all, query_one, utc_now_iso
from app.mocks.ledger.db import ledger_db
from app.tools import crm, notify, ops, refunds
from app.tools.client import record_case_event
from app.tools.registry import execute_action


class _ProactivePaymentAgentStub:
    NAME = "payment_failure"
    ALLOWLIST = {"initiate_refund"}


def get_open_incident_for_signature(signature: str) -> dict[str, Any] | None:
    return query_one(
        "SELECT * FROM incidents WHERE signature = ? AND status = 'OPEN' ORDER BY detected_at DESC LIMIT 1",
        (signature,),
    )


def record_complaint_signal(
    *,
    case_id: str,
    persona_id: str,
    txn: dict[str, Any] | None,
    source: str = "chat",
) -> dict[str, Any] | None:
    """
    Records a complaint signal ONLY when payment_failure diagnoses a verified FAILED + DEBITED + uncredited ledger row.
    """
    if not txn:
        return None
    if txn.get("status") != "FAILED" or txn.get("debit_status") != "DEBITED" or int(txn.get("credit_to_merchant", 0)) != 0:
        return None

    bank_code = str(txn.get("bank_code") or "BANK_TIMEOUT")
    rail = str(txn.get("rail") or "BILL_PAY")
    signature = f"{bank_code}|{rail}"
    merchant = str(txn.get("counterparty") or "Merchant")
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    execute(
        """
        INSERT INTO complaint_signals(ts, persona_id, case_id, signature, bank_code, merchant, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (now_iso, persona_id, case_id, signature, bank_code, merchant, source),
    )

    win_s = int(cfg_mgr.thresholds.get("incident_window_s", 120))
    min_signals = int(cfg_mgr.thresholds.get("incident_min_signals", 8))
    min_users = int(cfg_mgr.thresholds.get("incident_min_users", 6))

    cutoff = (now - timedelta(seconds=win_s)).isoformat()
    stats = query_one(
        """
        SELECT COUNT(*) AS sig_cnt,
               COUNT(DISTINCT persona_id) AS usr_cnt,
               MIN(ts) AS first_ts
        FROM complaint_signals
        WHERE signature = ? AND ts >= ?
        """,
        (signature, cutoff),
    )
    if not stats:
        return None

    sig_cnt = int(stats["sig_cnt"] or 0)
    usr_cnt = int(stats["usr_cnt"] or 0)
    first_ts = str(stats["first_ts"] or now_iso)

    existing_inc = get_open_incident_for_signature(signature)
    if existing_inc:
        execute(
            "UPDATE incidents SET signal_count = ?, user_count = ? WHERE id = ?",
            (sig_cnt, usr_cnt, existing_inc["id"]),
        )
        updated = query_one("SELECT * FROM incidents WHERE id = ?", (existing_inc["id"],)) or existing_inc
        bus.publish_console("incident_updated", {"incident": updated})
        return updated

    if sig_cnt >= min_signals and usr_cnt >= min_users:
        inc_id = next_id("incident")
        notice_tmpl = get_template_text("INCIDENT_NOTICE", "en")
        notice_text = notice_tmpl.format(bank_code=bank_code)
        execute(
            """
            INSERT INTO incidents(
                id, signature, bank_code, merchant, signal_count, user_count,
                first_signal_at, detected_at, status, notice_text, public_status, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, 0, NULL)
            """,
            (inc_id, signature, bank_code, merchant, sig_cnt, usr_cnt, first_ts, now_iso, notice_text),
        )
        created = query_one("SELECT * FROM incidents WHERE id = ?", (inc_id,)) or {}
        bus.publish_console("incident_updated", {"incident": created})
        return created

    return None


async def preview_incident(incident_id: str, actor: str = "human:A-1") -> dict[str, Any]:
    """
    Dry-run preview: calls ops_list_affected, evaluates policy per affected row without mutating state.
    """
    inc = query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not inc:
        raise ValueError(f"Incident {incident_id} not found")

    bank_code = inc["bank_code"]
    max_cases = int(cfg_mgr.thresholds.get("incident_bulk_max_cases", 50))
    aff_out = await ops.ops_list_affected(
        acting_user="OPS",
        actor=actor if actor.startswith("human:") else f"human:{actor}",
        bank_code=bank_code,
        since_hours=48.0,
    )
    rows = aff_out.data if (aff_out.ok and isinstance(aff_out.data, list)) else []
    rows = rows[:max_cases]

    pol_cfg = cfg_mgr.get_policy_config()
    agent_paused = cfg_mgr.is_agent_paused("payment_failure")

    preview_rows: list[dict[str, Any]] = []
    total_auto_amount = 0
    total_approve_amount = 0
    counts = {"AUTO": 0, "APPROVE": 0, "ESCALATE": 0, "EXCLUDED": 0}

    for r in rows:
        txn_id = r["txn_id"]
        user_id = r["user_id"]
        amt = int(r["amount"])
        cp = r["counterparty"]
        has_rf = bool(r.get("has_refund"))

        if has_rf:
            counts["EXCLUDED"] += 1
            preview_rows.append(
                {
                    "txn_id": txn_id,
                    "user_id": user_id,
                    "amount": amt,
                    "counterparty": cp,
                    "disposition": "EXCLUDED",
                    "rule": "ALREADY_REFUNDED",
                    "reason": "Refund already exists for this transaction",
                }
            )
            continue

        triggers = ["KS"] if agent_paused else []
        ctx = CasePolicyContext(
            case_id=f"PREVIEW-{txn_id}",
            persona_user=user_id,
            triggers=triggers,
            confidence=0.95,
        )
        prop = ProposedAction(
            name="initiate_refund",
            args={"txn_id": txn_id, "amount": amt},
            is_money=True,
            amount=amt,
            target_txn=txn_id,
            target_user=user_id,
        )
        dec = evaluate_policy(ctx, prop, _ProactivePaymentAgentStub(), pol_cfg)
        disp = dec.outcome
        counts[disp] = counts.get(disp, 0) + 1
        if disp == "AUTO":
            total_auto_amount += amt
        elif disp == "APPROVE":
            total_approve_amount += amt

        preview_rows.append(
            {
                "txn_id": txn_id,
                "user_id": user_id,
                "amount": amt,
                "counterparty": cp,
                "disposition": disp,
                "rule": dec.rule,
                "reason": dec.text,
            }
        )

    return {
        "incident": inc,
        "rows": preview_rows,
        "counts": counts,
        "total_rows": len(preview_rows),
        "total_auto_amount": total_auto_amount,
        "total_approve_amount": total_approve_amount,
        "total_amount": total_auto_amount + total_approve_amount,
    }


async def publish_incident_notice(incident_id: str, actor: str = "A-2") -> dict[str, Any]:
    inc = query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not inc:
        raise ValueError(f"Incident {incident_id} not found")

    bank_code = inc["bank_code"]
    execute("UPDATE incidents SET public_status = 1 WHERE id = ?", (incident_id,))

    # Find affected users and publish incident_notice
    aff_out = await ops.ops_list_affected(
        acting_user="OPS",
        actor=f"human:{actor}" if not actor.startswith("human:") else actor,
        bank_code=bank_code,
        since_hours=48.0,
    )
    rows = aff_out.data if (aff_out.ok and isinstance(aff_out.data, list)) else []
    seen_users: set[str] = set()
    personas = cfg_mgr.get_personas()
    for r in rows:
        uid = r["user_id"]
        if uid in seen_users:
            continue
        seen_users.add(uid)
        lang = personas.get(uid, {}).get("language", "en")
        notice_msg, _ = await compose_message("INCIDENT_NOTICE", {"bank_code": bank_code}, lang)
        bus.publish_customer(
            uid,
            "incident_notice",
            {
                "incident_id": incident_id,
                "bank_code": bank_code,
                "text": notice_msg,
                "template_code": "INCIDENT_NOTICE",
            },
        )

    updated = query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,)) or inc
    bus.publish_console("incident_updated", {"incident": updated})
    return updated


async def resolve_incident(incident_id: str, actor: str = "A-2") -> dict[str, Any]:
    """
    Proactively resolves affected cohort rows for an incident:
    - Creates source='PROACTIVE' cases for unrefunded affected transactions
    - Runs policy + execute + verify + compose(PROACTIVE_REFUND) + notify
    - Approves any pending approval rows for this incident signature with human:<actor>
    - Deduplicates via deterministic idempotency keys so zero duplicate refunds ever occur
    """
    inc = query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    if not inc:
        raise ValueError(f"Incident {incident_id} not found")

    human_actor = actor if actor.startswith("human:") else f"human:{actor}"
    bank_code = inc["bank_code"]
    max_cases = int(cfg_mgr.thresholds.get("incident_bulk_max_cases", 50))

    aff_out = await ops.ops_list_affected(
        acting_user="OPS",
        actor=human_actor,
        bank_code=bank_code,
        since_hours=48.0,
    )
    rows = aff_out.data if (aff_out.ok and isinstance(aff_out.data, list)) else []
    rows = rows[:max_cases]

    pol_cfg = cfg_mgr.get_policy_config()
    agent_paused = cfg_mgr.is_agent_paused("payment_failure")
    personas = cfg_mgr.get_personas()

    actions_logged: list[dict[str, Any]] = []
    refunded_count = 0
    skipped_count = 0

    for r in rows:
        txn_id = r["txn_id"]
        user_id = r["user_id"]
        amt = int(r["amount"])
        cp = r["counterparty"]

        # Authoritative check: does a refund already exist for this txn_id?
        rf_check = await refunds.get_refund_for_txn(acting_user=user_id, txn_id=txn_id, emit_trace=False)
        existing_rfs = rf_check.data if (rf_check.ok and isinstance(rf_check.data, list)) else []
        if existing_rfs:
            skipped_count += 1
            execute(
                """
                INSERT INTO incident_actions(incident_id, persona_id, case_id, action, outcome, ts)
                VALUES (?, ?, ?, 'skip_existing_refund', 'SKIPPED_ALREADY_REFUNDED', ?)
                """,
                (incident_id, user_id, existing_rfs[0].get("case_hint") or "", utc_now_iso()),
            )
            continue

        if agent_paused:
            skipped_count += 1
            execute(
                """
                INSERT INTO incident_actions(incident_id, persona_id, case_id, action, outcome, ts)
                VALUES (?, ?, '', 'skip_paused_agent', 'SKIPPED_PAUSED', ?)
                """,
                (incident_id, user_id, utc_now_iso()),
            )
            continue

        # Check if there is an existing case awaiting approval for this transaction
        existing_case = query_one(
            "SELECT * FROM cases WHERE persona_id = ? AND state = 'AWAITING_APPROVAL' AND masked_text LIKE ?",
            (user_id, f"%{txn_id}%"),
        )
        lang = personas.get(user_id, {}).get("language", "en")
        now_iso = utc_now_iso()

        if existing_case:
            case_id = existing_case["id"]
        else:
            case_id = next_id("case")
            execute(
                """
                INSERT INTO cases(
                    id, parent_id, persona_id, source, state, agent, intent, language, sentiment,
                    outcome, rule_fired, trigger, diagnosis, owner_id, masked_text, extraction_json,
                    guard_hit, clarification_used, created_at, closed_at, lane, reopened, confidence, confidence_band
                ) VALUES (?, NULL, ?, 'PROACTIVE', 'EXECUTING', 'payment_failure', 'PAYMENT_FAILED_DEBITED', ?, 'calm',
                          'AUTO', '3', '', 'REFUND_DUE', '', ?, '{}', 0, 0, ?, NULL, 'amber', 0, 0.96, 'high')
                """,
                (case_id, user_id, lang, f"[PROACTIVE {incident_id}] {txn_id} ₹{amt} at {cp}", now_iso),
            )

        ctx = CasePolicyContext(
            case_id=case_id,
            persona_user=user_id,
            triggers=[],
            confidence=0.96,
            velocity_count_24h=0,
            velocity_amount_24h=0,
        )
        prop = ProposedAction(
            name="initiate_refund",
            args={"txn_id": txn_id, "amount": amt},
            is_money=True,
            amount=amt,
            target_txn=txn_id,
            target_user=user_id,
        )
        dec = evaluate_policy(ctx, prop, _ProactivePaymentAgentStub(), pol_cfg)

        if dec.outcome in ("ESCALATE", "BLOCK"):
            skipped_count += 1
            execute(
                "UPDATE cases SET state = 'ESCALATED', outcome = 'ESCALATE', rule_fired = ?, trigger = ? WHERE id = ?",
                (dec.rule, dec.rule, case_id),
            )
            execute(
                """
                INSERT INTO incident_actions(incident_id, persona_id, case_id, action, outcome, ts)
                VALUES (?, ?, ?, 'skip_escalated', ?, ?)
                """,
                (incident_id, user_id, case_id, f"SKIPPED_{dec.rule}", now_iso),
            )
            continue

        # If APPROVE, the ops_lead click on Resolve Incident approves it with full audit logging
        exec_actor = "saathi"
        if dec.outcome == "APPROVE":
            exec_actor = human_actor
            app_id = next_id("approval")
            execute(
                """
                INSERT INTO approvals(
                    id, case_id, proposed_action_json, rule_fired, status, decided_by,
                    reason_code, reason_text, created_at, decided_at
                ) VALUES (?, ?, ?, ?, 'APPROVED', ?, 'INCIDENT_BULK', ?, ?, ?)
                """,
                (
                    app_id,
                    case_id,
                    f'{{"name":"initiate_refund","args":{{"txn_id":"{txn_id}","amount":{amt}}}}}',
                    dec.rule,
                    human_actor,
                    f"bulk incident {incident_id}",
                    now_iso,
                    now_iso,
                ),
            )
            execute(
                """
                INSERT INTO autonomy_decisions(ts, agent, case_id, mode, agreed, decided_by, source)
                VALUES (?, 'payment_failure', ?, 'guarded', 1, ?, 'live')
                """,
                (now_iso, case_id, human_actor),
            )

        idem_key = f"PROACTIVE|{txn_id}|{amt}"
        w_out = await execute_action(
            action_name="initiate_refund",
            args={"txn_id": txn_id, "amount": amt},
            acting_user=user_id,
            case_id=case_id,
            actor=exec_actor,
            idempotency_key=idem_key,
        )
        if not w_out.ok:
            skipped_count += 1
            continue

        ver_res = await verify_and_recover(
            case_id=case_id,
            action_name="initiate_refund",
            args={"txn_id": txn_id, "amount": amt},
            write_outcome=w_out,
            acting_user=user_id,
            actor=exec_actor,
        )
        if not ver_res.verified:
            skipped_count += 1
            continue

        rf_data = ver_res.data or (w_out.data if isinstance(w_out.data, dict) else {})
        refund_id = str(rf_data.get("id") or "RF-9001")
        refunded_count += 1

        register_followup_check(
            case_id=case_id,
            kind="REFUND_COMPLETED",
            due_hours=72.25,
            target_id=refund_id,
            txn_id=txn_id,
        )

        txn_full = ledger_db.query_one("SELECT * FROM transactions WHERE id = ?", (txn_id,))
        await check_and_record_tat_compensation(case_id=case_id, txn=txn_full, language=lang)

        msg_text, _ = await compose_message(
            "PROACTIVE_REFUND",
            {
                "amount": amt,
                "counterparty": cp,
                "txn_id": txn_id,
                "refund_id": refund_id,
                "sla_hours": 72,
            },
            lang,
            case_id=case_id,
        )
        await notify.send_message(acting_user=user_id, message=msg_text, case_id=case_id, actor="incident-monitor")
        bus.publish_customer(
            user_id,
            "resolution",
            {
                "case_id": case_id,
                "text": msg_text,
                "template_code": "PROACTIVE_REFUND",
                "proactive": True,
                "found": f"₹{amt} was debited for {txn_id} ({cp}) during a bank-side incident.",
                "did": f"Proactively started refund {refund_id} for ₹{amt}.",
                "next": "Expected in your account within 72 hours.",
            },
            case_id=case_id,
        )

        execute(
            "UPDATE cases SET state = 'CLOSED', closed_at = ?, outcome = ? WHERE id = ?",
            (now_iso, dec.outcome, case_id),
        )
        await crm.sync_crm_case(
            acting_user=user_id,
            case_id=case_id,
            agent="payment_failure",
            state="CLOSED",
            outcome="PROACTIVE_REFUND",
        )
        execute(
            """
            INSERT INTO incident_actions(incident_id, persona_id, case_id, action, outcome, ts)
            VALUES (?, ?, ?, 'initiate_refund', 'VERIFIED', ?)
            """,
            (incident_id, user_id, case_id, now_iso),
        )
        actions_logged.append({"case_id": case_id, "persona_id": user_id, "txn_id": txn_id, "refund_id": refund_id, "amount": amt})

    res_ts = utc_now_iso()
    execute(
        "UPDATE incidents SET status = 'RESOLVED', resolved_at = ? WHERE id = ?",
        (res_ts, incident_id),
    )
    updated_inc = query_one("SELECT * FROM incidents WHERE id = ?", (incident_id,)) or inc
    bus.publish_console("incident_updated", {"incident": updated_inc})

    return {
        "incident": updated_inc,
        "refunded_count": refunded_count,
        "skipped_count": skipped_count,
        "actions": actions_logged,
    }
