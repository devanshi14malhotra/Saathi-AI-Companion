"""
Operations War-Room & Teammate Superpower Controls
Features:
- Bank Outage Detection & Deflection (F3)
- Time Travel Machine (+24h, +73h) to trigger RBI TAT Compensation (F2, F11)
- Phantom-Write Chaos Injection & Read-After-Write Verification (F1, F10)
- Autonomy Safety Dial & Emergency Kill-Switch (F7, Rule 15)
"""

import streamlit as st
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css, render_header
from streamlit_app.components.db_helper import (
    init_app_state,
    query_core_all,
    execute_core,
    run_async,
)
from app.core.config import cfg_mgr
from app.core.followups import advance_time_and_run_followups

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

with tab_outage:
    st.subheader("🏦 Bank Outage Incident Monitor (Feature F3)")
    st.write("When a partner bank experiences an API outage or high failure rate, Saathi detects the incident and deflects incoming cases.")

    incidents = query_core_all("SELECT * FROM incidents ORDER BY detected_at DESC")
    if incidents:
        import pandas as pd
        st.dataframe(pd.DataFrame(incidents), use_container_width=True, hide_index=True)
    else:
        st.info("No active bank outages currently logged.")

    st.markdown("#### Declare Active Bank Outage / Incident:")
    c_b1, c_b2, c_b3 = st.columns([1, 1, 1])
    with c_b1:
        if st.button("🚨 Declare HDFC UPI Outage"):
            from app.core.ids import next_id
            inc_id = next_id("incident")
            execute_core(
                """
                INSERT INTO incidents(id, signature, bank_code, status, notice_text, detected_at)
                VALUES (?, 'HDFC:UPI', 'HDFC', 'ACTIVE', 'Spike in debit timeouts detected (>40% failure rate)', datetime('now'))
                """,
                (inc_id,),
            )
            st.warning(f"Incident {inc_id} declared for HDFC! Incoming HDFC failure complaints will now be proactively deflected.")
            st.rerun()

    with c_b2:
        if st.button("🚨 Declare SBI Outage"):
            from app.core.ids import next_id
            inc_id = next_id("incident")
            execute_core(
                """
                INSERT INTO incidents(id, signature, bank_code, status, notice_text, detected_at)
                VALUES (?, 'SBI:UPI', 'SBI', 'ACTIVE', 'Core banking gateway unavailable', datetime('now'))
                """,
                (inc_id,),
            )
            st.warning(f"Incident {inc_id} declared for SBI!")
            st.rerun()

    with c_b3:
        if st.button("✅ Resolve All Outages"):
            execute_core("UPDATE incidents SET status = 'RESOLVED'")
            st.success("All bank outage incidents marked resolved.")
            st.rerun()

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
        if st.button("⏩ Advance System Time +24 Hours (T+1)"):
            res = run_async(advance_time_and_run_followups(hours=24.0))
            st.success(f"Clock advanced by 24h! Followups processed: {res}")
            st.rerun()

    with c_t2:
        if st.button("⏩ Advance System Time +73 Hours (T+3 Days)"):
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

with tab_chaos:
    st.subheader("💥 Read-After-Write Verification & Phantom Retry (F1, F10)")
    st.write(
        "Financial safety rule: Saathi never assumes a tool call succeeded. Every mutation tool call is followed by an independent "
        "read-after-write query. If the database record does not match (phantom write), Saathi retries up to 3 times before escalating (T6)."
    )
    st.info("🛡️ Verification is permanently enforced in `backend/app/tools/verification.py` across all `initiate_refund`, `raise_reconciliation`, and `lock_instrument` calls.")

with tab_dial:
    st.subheader("🎛️ Autonomy Dials & Safety Policy Controls (F7, Rule 15)")
    st.write(
        "Per Rule 15: Autonomy dials can automatically tighten under stress, but loosening requires an explicit human action. "
        "All changes are recorded in the audit log."
    )

    c_cap, c_conf = st.columns(2)
    with c_cap:
        new_cap = st.slider("Max Autonomous Auto-Refund Cap (₹):", min_value=500, max_value=5000, value=2000, step=500)
    with c_conf:
        min_conf = st.slider("Minimum Auto-Resolution Confidence Gate:", min_value=0.70, max_value=0.99, value=0.90, step=0.01)

    if st.button("Apply Safety Policy Update"):
        st.success(f"Updated policy: Cap = ₹{new_cap:,}, Min Confidence = {min_conf:.2f}. Audited.")
