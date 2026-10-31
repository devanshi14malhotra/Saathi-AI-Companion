"""
Operations War-Room & Teammate Superpower Controls
Features:
- Bank Outage Detection & Deflection (F3) with Dry-Run Impact Preview & 1-Click Proactive Resolution
- Time Travel Machine (+24h, +73h) to trigger RBI TAT Compensation (F2, F11)
- Phantom-Write Chaos Injection & Read-After-Write Verification (F1, F10)
- Autonomy Safety Dial & Emergency Kill-Switch (F7, Rule 15) with Audit History
"""

import streamlit as st
import sys
import json
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css, render_header, render_metric_card
from streamlit_app.components.db_helper import (
    init_app_state,
    query_core_all,
    query_core_one,
    execute_core,
    run_async,
)
from app.core.config import cfg_mgr
from app.core.ids import next_id
from app.core.followups import advance_time_and_run_followups
from app.core.incidents import preview_incident, resolve_incident, publish_incident_notice
from app.mocks.refunds.app import refunds_sim

st.set_page_config(page_title="Operations War-Room | Paytm Saathi", page_icon="⚡", layout="wide")
inject_custom_css()
init_app_state()

render_header(
    title="Operations War-Room & Teammate Superpowers",
    subtitle="Manage bank gateway downtime, fast-forward time to trigger RBI compensations, and monitor resilience",
    badge="Operations Lead",
)

tab_outage, tab_time, tab_chaos, tab_dial = st.tabs([
    "🏦 Bank Outages & Deflection",
    "⏰ Time Travel & RBI TAT Claims",
    "💥 Chaos & Verification Retry",
    "🎛️ Autonomy Dials & Kill Switch",
])

# ---------------------------------------------------------
# TAB 1: BANK OUTAGES & PROACTIVE RESOLUTION (F3)
# ---------------------------------------------------------
with tab_outage:
    st.subheader("🏦 Bank Outage Incident Monitor & Deflection (Feature F3)")
    st.write(
        "When partner banks experience gateway downtime or high failure rates, Saathi detects the signature, "
        "deflects incoming complaints with public notices, and allows operations to execute **Proactive Bulk Refunds**."
    )

    incidents = query_core_all("SELECT * FROM incidents ORDER BY detected_at DESC")
    open_incidents = [i for i in incidents if i.get("status") == "OPEN"]

    if incidents:
        import pandas as pd
        st.dataframe(
            pd.DataFrame(incidents)[[
                "id", "signature", "bank_code", "status", "signal_count", "user_count", "public_status", "detected_at"
            ]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Incident ID", width="small"),
                "signature": st.column_config.TextColumn("Signature", width="small"),
                "bank_code": st.column_config.TextColumn("Bank", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "signal_count": st.column_config.NumberColumn("Signals"),
                "user_count": st.column_config.NumberColumn("Users Affected"),
                "public_status": st.column_config.CheckboxColumn("Public Banner"),
            },
        )
    else:
        st.info("No active bank outages currently logged.")

    st.markdown("---")
    st.markdown("#### 🚨 Declare Gateway Outage / Cluster Simulation:")
    c_b1, c_b2, c_b3 = st.columns([1, 1, 1])

    with c_b1:
        if st.button("🚨 Declare HDFC UPI Outage", type="secondary", use_container_width=True):
            inc_id = next_id("incident")
            sig = "HDFC|UPI"
            notice = "HDFC Bank UPI gateway experiencing high debit timeouts (>40%). Proactive auto-refunds active."
            execute_core(
                """
                INSERT OR REPLACE INTO incidents(
                    id, signature, bank_code, merchant, signal_count, user_count,
                    first_signal_at, detected_at, status, notice_text, public_status, resolved_at
                ) VALUES (?, ?, 'HDFC', 'All Merchants', 12, 8, datetime('now'), datetime('now'), 'OPEN', ?, 1, NULL)
                """,
                (inc_id, sig, notice),
            )
            st.warning(f"Incident {inc_id} declared for HDFC! Signature '{sig}' will proactively deflect incoming complaints.")
            st.rerun()

    with c_b2:
        if st.button("🚨 Declare SBI UPI Outage", type="secondary", use_container_width=True):
            inc_id = next_id("incident")
            sig = "SBI|UPI"
            notice = "SBI core banking gateway unavailable. Reversals queued automatically."
            execute_core(
                """
                INSERT OR REPLACE INTO incidents(
                    id, signature, bank_code, merchant, signal_count, user_count,
                    first_signal_at, detected_at, status, notice_text, public_status, resolved_at
                ) VALUES (?, ?, 'SBI', 'All Merchants', 15, 10, datetime('now'), datetime('now'), 'OPEN', ?, 1, NULL)
                """,
                (inc_id, sig, notice),
            )
            st.warning(f"Incident {inc_id} declared for SBI! Signature '{sig}' active.")
            st.rerun()

    with c_b3:
        if st.button("✅ Mark All Outages Resolved", use_container_width=True):
            execute_core("UPDATE incidents SET status = 'RESOLVED', resolved_at = datetime('now') WHERE status = 'OPEN'")
            st.success("All bank outage incidents marked resolved.")
            st.rerun()

    # Proactive Resolution Section for Open Outages
    if open_incidents:
        st.markdown("---")
        st.markdown("### ⚡ Proactive Outage Resolution (Beat 3 · It Acts Before Complaints)")
        st.write("Inspect affected transactions across the fleet without writing (Dry-Run), then resolve in bulk with verified refunds.")

        target_inc = open_incidents[0]
        inc_id = target_inc["id"]
        bank = target_inc.get("bank_code", "HDFC")

        col_pr1, col_pr2 = st.columns([1, 1])

        with col_pr1:
            if st.button(f"🔍 Dry-Run Impact Preview for {inc_id} ({bank})", type="primary", use_container_width=True):
                try:
                    preview_data = run_async(preview_incident(inc_id, actor="human:OPS_LEAD"))
                    st.session_state[f"preview_{inc_id}"] = preview_data
                except Exception as e:
                    st.error(f"Preview failed: {e}")

        with col_pr2:
            if st.button(f"🚀 Resolve Incident & Issue Proactive Refunds ({inc_id})", use_container_width=True):
                try:
                    with st.spinner("Executing verified bulk refunds across isolated microservices..."):
                        res_data = run_async(resolve_incident(inc_id, actor="human:OPS_LEAD"))
                        st.success(
                            f"✅ Incident {inc_id} Resolved! "
                            f"Refunds Disbursed & Verified: {res_data.get('refunded_count', 0)} | "
                            f"Skipped / Already Handled: {res_data.get('skipped_count', 0)}"
                        )
                        st.session_state.pop(f"preview_{inc_id}", None)
                        st.rerun()
                except Exception as e:
                    st.error(f"Resolution failed: {e}")

        # Display Dry-Run Preview Table if available
        if f"preview_{inc_id}" in st.session_state:
            p_data = st.session_state[f"preview_{inc_id}"]
            st.markdown(f"#### 📋 Dry-Run Preview Results for `{inc_id}`:")
            p_m1, p_m2, p_m3, p_m4 = st.columns(4)
            with p_m1:
                render_metric_card("Total Affected", f"{p_data.get('total_rows', 0)}", "Identified in ledger")
            with p_m2:
                render_metric_card("Auto-Refunds", f"{p_data.get('counts', {}).get('AUTO', 0)}", "Under policy cap")
            with p_m3:
                render_metric_card("Over-Cap Reviews", f"{p_data.get('counts', {}).get('APPROVE', 0)}", "Held for supervisor")
            with p_m4:
                render_metric_card("Total Exposure", f"₹{p_data.get('total_amount', 0):,}", "To disburse")

            affected_cases = p_data.get("rows", [])
            if affected_cases:
                import pandas as pd
                st.dataframe(pd.DataFrame(affected_cases), use_container_width=True, hide_index=True)


# ---------------------------------------------------------
# TAB 2: TIME TRAVEL & RBI COMPENSATION (F2, F11)
# ---------------------------------------------------------
with tab_time:
    st.subheader("⏰ Time-Travel & Autonomous RBI TAT Compensation (F2, F11)")
    st.write(
        "Under RBI circular guidelines, if a failed debit is not credited/reversed within T+1 days, "
        "Paytm Saathi autonomously computes compensation at **₹100 per day** of delay and creates a claim without human intervention."
    )

    from datetime import datetime, timezone
    st.metric("System UTC Time", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    c_t1, c_t2 = st.columns(2)
    with c_t1:
        if st.button("⏩ Advance System Time +24 Hours (T+1)", use_container_width=True):
            res = run_async(advance_time_and_run_followups(hours=24.0))
            st.success(f"Clock advanced by 24h! Followups processed: {res}")
            st.rerun()

    with c_t2:
        if st.button("⏩ Advance System Time +73 Hours (T+3 Days)", use_container_width=True):
            res = run_async(advance_time_and_run_followups(hours=73.0))
            st.success(f"Clock advanced by 73h! Triggered TAT compensations: {res}")
            st.rerun()

    st.markdown("#### Live RBI TAT Compensation Claims (`compensation_claims` table):")
    claims = query_core_all("SELECT * FROM compensation_claims ORDER BY created_at DESC")
    if claims:
        import pandas as pd
        st.dataframe(
            pd.DataFrame(claims)[["id", "case_id", "txn_id", "days_late", "amount_estimate", "status", "created_at"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "amount_estimate": st.column_config.NumberColumn("Compensation Paid", format="₹%d"),
                "days_late": st.column_config.NumberColumn("Days Delayed"),
            },
        )
    else:
        st.caption("No compensation claims triggered yet. Test a delayed scenario (e.g. S28) and advance the clock.")


# ---------------------------------------------------------
# TAB 3: CHAOS & OUTCOME VERIFICATION (F1, F10)
# ---------------------------------------------------------
with tab_chaos:
    st.subheader("💥 Read-After-Write Verification & Phantom Retry (F1, F10)")
    st.write(
        "Financial safety invariant: Saathi never assumes a tool call succeeded. Every mutation tool call is followed by an independent "
        "read-after-write query (enforced in `backend/app/core/verify.py`). If the database record is missing (phantom write) or mismatched, "
        "Saathi retries with an idempotency key up to 3 times before escalating (T6)."
    )

    p_count = refunds_sim.pending_phantoms_count()
    f_count = refunds_sim.pending_failures_count()

    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        render_metric_card("Armed Phantom Writes", f"{p_count}", "Simulates HTTP 201 without DB insert")
    with ch2:
        render_metric_card("Armed Timeouts", f"{f_count}", "Simulates 504 Gateway Timeouts")
    with ch3:
        render_metric_card("Stuck TXN Traps", f"{len(refunds_sim.stuck_txn_ids)}", "Simulates delayed settlement")

    st.markdown("#### Interactive Chaos Injection Controls (Live Demonstration):")
    col_c1, col_c2, col_c3 = st.columns(3)

    with col_c1:
        if st.button("💣 Arm Phantom 201 on Next Refund", use_container_width=True):
            refunds_sim.phantom_rules.append({"count": 1, "method": "POST"})
            st.warning("Armed! The next refund request will return HTTP 201 but will NOT insert a row into refunds.db. Saathi's read-after-write verification will catch this phantom write and recover safely!")
            st.rerun()

    with col_c2:
        if st.button("⏱️ Arm 504 Timeout on Next Refund", use_container_width=True):
            refunds_sim.fail_rules.append({"count": 1, "mode": "timeout", "method": "POST"})
            st.warning("Armed! The next refund request will simulate a 504 timeout. Saathi will retry with idempotency key without duplicate debits.")
            st.rerun()

    with col_c3:
        if st.button("🔄 Clear All Armed Chaos Faults", use_container_width=True):
            refunds_sim.reset()
            st.success("All chaos simulation rules cleared.")
            st.rerun()


# ---------------------------------------------------------
# TAB 4: AUTONOMY DIALS & KILL-SWITCH (F7, Rule 15)
# ---------------------------------------------------------
with tab_dial:
    st.subheader("🎛️ Autonomy Dials & Safety Policy Controls (F7, Rule 15)")
    st.write(
        "Per Rule 15: Policy threshold changes and emergency kill-switches are stored in `config_state` and logged in `config_audit`."
    )

    pol_cfg = cfg_mgr.get_policy_config()
    current_cap = pol_cfg.modes.get("guarded", {}).get("auto_cap", 5000)
    current_conf = pol_cfg.min_auto_confidence

    # 1. Autonomy Threshold Controls
    st.markdown("#### 1. Live Policy Threshold Adjustments:")
    c_cap, c_conf = st.columns(2)
    with c_cap:
        new_cap = st.slider("Max Autonomous Auto-Refund Cap (₹):", min_value=500, max_value=15000, value=current_cap, step=500)
    with c_conf:
        min_conf = st.slider("Minimum Auto-Resolution Confidence Gate:", min_value=0.60, max_value=0.99, value=current_conf, step=0.01)

    if st.button("Apply Safety Policy Update", type="primary"):
        cfg_mgr.set_threshold_override("guarded_auto_cap", new_cap, actor="OPS_LEAD")
        cfg_mgr.set_threshold_override("min_auto_confidence", min_conf, actor="OPS_LEAD")
        st.success(f"✅ Policy updated and audited: Cap = ₹{new_cap:,}, Min Confidence = {min_conf:.2f}")
        st.rerun()

    st.markdown("---")

    # 2. Emergency Kill-Switches
    st.markdown("#### 2. Emergency Money-Action Kill-Switches:")
    killswitches = cfg_mgr.get_killswitches()

    ks_col1, ks_col2, ks_col3 = st.columns(3)
    with ks_col1:
        all_paused = killswitches.get("all", False)
        if st.toggle("🚨 Kill-Switch: ALL Money Actions", value=all_paused):
            if not all_paused:
                cfg_mgr.set_killswitch("all", True, actor="OPS_LEAD")
                st.rerun()
        else:
            if all_paused:
                cfg_mgr.set_killswitch("all", False, actor="OPS_LEAD")
                st.rerun()

    with ks_col2:
        pf_paused = killswitches.get("payment_failure", False)
        if st.toggle("⏸️ Pause Payment Failure Agent", value=pf_paused):
            if not pf_paused:
                cfg_mgr.set_killswitch("payment_failure", True, actor="OPS_LEAD")
                st.rerun()
        else:
            if pf_paused:
                cfg_mgr.set_killswitch("payment_failure", False, actor="OPS_LEAD")
                st.rerun()

    with ks_col3:
        rf_paused = killswitches.get("refund", False)
        if st.toggle("⏸️ Pause Refund Specialist", value=rf_paused):
            if not rf_paused:
                cfg_mgr.set_killswitch("refund", True, actor="OPS_LEAD")
                st.rerun()
        else:
            if rf_paused:
                cfg_mgr.set_killswitch("refund", False, actor="OPS_LEAD")
                st.rerun()

    st.markdown("---")

    # 3. Policy Audit History
    st.markdown("#### 📜 Policy Audit History (`config_audit` table):")
    audits = query_core_all("SELECT * FROM config_audit ORDER BY id DESC LIMIT 15")
    if audits:
        import pandas as pd
        st.dataframe(pd.DataFrame(audits)[["id", "ts", "actor", "key", "old", "new"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No policy changes audited yet.")
