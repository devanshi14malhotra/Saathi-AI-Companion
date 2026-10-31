"""
Operations & Gateway Incident Management Workspace
Features:
- Bank outage incident monitoring and proactive bulk resolution
- Time-travel machine to advance clock and evaluate RBI TAT delay compensations
- Read-after-write verification log proving outcome verification
- Autonomy mode configuration, emergency kill-switches, and audit log
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, status_chip, id_chip, kpi
from streamlit_app.components.db_helper import (
    init_app_state,
    query_core_all,
    query_core_one,
    run_async,
)
from app.core.config import cfg_mgr
from app.core.followups import advance_time_and_run_followups
from app.core.incidents import preview_incident, resolve_incident

st.set_page_config(page_title="Operations | Saathi", page_icon="⚡", layout="wide")
inject_custom_css()
init_app_state()

page_header(
    title="Operations",
    subtitle="Incident deflection, time-travel compensation simulations, verification log, and autonomy safety controls",
)

tab_incidents, tab_time, tab_verify, tab_autonomy = st.tabs([
    "Incidents",
    "Time travel (demo)",
    "Verification log",
    "Autonomy and kill switch",
])

# ---------------------------------------------------------
# TAB 1: INCIDENTS
# ---------------------------------------------------------
with tab_incidents:
    st.markdown("### Bank gateway incidents")

    min_sig = cfg_mgr.thresholds.get("incident_min_signals", 8)
    min_usr = cfg_mgr.thresholds.get("incident_min_users", 6)
    win_s = cfg_mgr.thresholds.get("incident_window_s", 120)

    st.markdown(
        f"""
        <div style="background: #F7F8FA; border: 1px solid #E5E7EB; border-radius: 8px; padding: 0.65rem 0.85rem; font-size: 13px; color: #4B5563; margin-bottom: 1rem;">
            Automatic incident detection threshold: <b>{min_sig} signals</b> from at least <b>{min_usr} distinct users</b> within a <b>{win_s}-second window</b>. When detected, public notices deflect customer inquiries and proactive refunds are triggered.
        </div>
        """,
        unsafe_allow_html=True,
    )

    incidents = query_core_all("SELECT * FROM incidents ORDER BY detected_at DESC")

    if incidents:
        df_inc = pd.DataFrame(incidents)
        # Drop empty columns
        non_empty = [col for col in df_inc.columns if df_inc[col].notna().any() and (df_inc[col] != "").any()]
        show_cols = [c for c in ["id", "signature", "bank_code", "status", "signal_count", "user_count", "detected_at", "notice_text"] if c in non_empty]

        st.dataframe(
            df_inc[show_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Incident ID", width="small"),
                "signature": st.column_config.TextColumn("Signature", width="small"),
                "bank_code": st.column_config.TextColumn("Bank", width="small"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "signal_count": st.column_config.NumberColumn("Signals"),
                "user_count": st.column_config.NumberColumn("Users affected"),
                "detected_at": st.column_config.TextColumn("Detected at", width="medium"),
                "notice_text": st.column_config.TextColumn("Notice message", width="large"),
            },
        )

        open_incidents = [i for i in incidents if i.get("status") == "OPEN"]
        if open_incidents:
            st.write("")
            st.markdown("### Proactive incident resolution")
            for inc in open_incidents:
                inc_id = inc["id"]
                bank = inc.get("bank_code", "Bank")
                st.markdown(f"**Open incident {id_chip(inc_id)}** ({bank})", unsafe_allow_html=True)

                col_prev, col_res, _ = st.columns([1.5, 1.5, 3])
                with col_prev:
                    if st.button(f"Dry-run preview ({inc_id})", key=f"prev_{inc_id}"):
                        try:
                            preview_data = run_async(preview_incident(inc_id, actor="OPS_LEAD"))
                            st.session_state[f"preview_{inc_id}"] = preview_data
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Preview failed: {exc}")

                with col_res:
                    if st.button(f"Resolve and issue refunds ({inc_id})", key=f"res_{inc_id}", type="primary"):
                        try:
                            with st.spinner("Processing bulk proactive refunds..."):
                                res = run_async(resolve_incident(inc_id, actor="OPS_LEAD"))
                                st.toast(f"Incident {inc_id} resolved: {res.get('refunded_count', 0)} refunds issued.")
                                st.session_state.pop(f"preview_{inc_id}", None)
                                st.rerun()
                        except Exception as exc:
                            st.error(f"Resolution failed: {exc}")

                if f"preview_{inc_id}" in st.session_state:
                    pdata = st.session_state[f"preview_{inc_id}"]
                    st.markdown("<div style='font-size: 13px; font-weight: 600; margin-top: 8px;'>Preview summary</div>", unsafe_allow_html=True)
                    pm1, pm2, pm3 = st.columns(3)
                    with pm1:
                        kpi("Affected rows", f"{pdata.get('total_rows', 0)}")
                    with pm2:
                        kpi("Auto-refunds", f"{pdata.get('counts', {}).get('AUTO', 0)}")
                    with pm3:
                        kpi("Exposure", f"₹{pdata.get('total_amount', 0):,}")

                    rows = pdata.get("rows", [])
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No gateway incidents currently logged.")


# ---------------------------------------------------------
# TAB 2: TIME TRAVEL (DEMO)
# ---------------------------------------------------------
with tab_time:
    st.markdown("### Time travel simulation (demo)")
    st.write(
        "Simulate passage of time to trigger RBI TAT compensation claims (₹100/day for delays exceeding T+1 days) "
        "and execute scheduled closed-loop follow-up checks."
    )

    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.markdown(f"<div style='font-size: 13px; color: #6B7280; margin-bottom: 12px;'>Current system time: <b>{utc_now}</b></div>", unsafe_allow_html=True)

    col_t1, col_t2, _ = st.columns([1.5, 1.5, 3])
    with col_t1:
        if st.button("Advance +24 hours (T+1) (demo)", key="btn_tt_24"):
            with st.spinner("Advancing clock by 24h..."):
                res = run_async(advance_time_and_run_followups(hours=24.0))
                st.toast(f"Clock advanced 24h. Processed followups: {res}")
                st.rerun()

    with col_t2:
        if st.button("Advance +73 hours (T+3) (demo)", key="btn_tt_73"):
            with st.spinner("Advancing clock by 73h..."):
                res = run_async(advance_time_and_run_followups(hours=73.0))
                st.toast(f"Clock advanced 73h. Compensations checked: {res}")
                st.rerun()

    st.write("")
    st.markdown("### RBI TAT compensation claims")
    claims = query_core_all("SELECT * FROM compensation_claims ORDER BY created_at DESC")
    if claims:
        df_cl = pd.DataFrame(claims)
        cols_cl = ["id", "case_id", "txn_id", "days_late", "amount_estimate", "status", "created_at"]
        valid_cl = [c for c in cols_cl if c in df_cl.columns]
        st.dataframe(
            df_cl[valid_cl],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Claim ID", width="small"),
                "case_id": st.column_config.TextColumn("Case", width="small"),
                "txn_id": st.column_config.TextColumn("Transaction", width="small"),
                "days_late": st.column_config.NumberColumn("Days delayed"),
                "amount_estimate": st.column_config.NumberColumn("Amount (₹)", format="₹%d"),
                "status": st.column_config.TextColumn("Status", width="small"),
                "created_at": st.column_config.TextColumn("Created at", width="medium"),
            },
        )
    else:
        st.caption("No compensation claims recorded.")

    st.write("")
    st.markdown("### Follow-up checks")
    checks = query_core_all("SELECT * FROM followup_checks ORDER BY id DESC LIMIT 20")
    if checks:
        df_ck = pd.DataFrame(checks)
        st.dataframe(df_ck, use_container_width=True, hide_index=True)
    else:
        st.caption("No follow-up checks currently scheduled.")


# ---------------------------------------------------------
# TAB 3: VERIFICATION LOG
# ---------------------------------------------------------
with tab_verify:
    st.markdown("### Outcome verification log")
    st.write(
        "Proof of closed-loop verification: every state-mutating tool call is followed by an independent read-after-write check "
        "to ensure downstream microservice persistence before customer notification."
    )

    verify_events = query_core_all(
        """
        SELECT id, case_id, seq, badge, type, summary, ts
        FROM case_events
        WHERE badge = '[VERIFY] ✓'
        ORDER BY id DESC
        LIMIT 50
        """
    )

    if verify_events:
        df_v = pd.DataFrame(verify_events)
        st.dataframe(
            df_v[["id", "case_id", "badge", "summary", "ts"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Event ID", width="small"),
                "case_id": st.column_config.TextColumn("Case ID", width="small"),
                "badge": st.column_config.TextColumn("Verification badge", width="small"),
                "summary": st.column_config.TextColumn("Outcome summary", width="large"),
                "ts": st.column_config.TextColumn("Verified at", width="medium"),
            },
        )
    else:
        st.caption("Read-after-write verification entries will appear here as tool calls execute.")


# ---------------------------------------------------------
# TAB 4: AUTONOMY & KILL SWITCH
# ---------------------------------------------------------
with tab_autonomy:
    st.markdown("### Autonomy modes")
    st.write("Configure each specialist agent's autonomy tier and financial action ceiling.")

    pol_cfg = cfg_mgr.get_policy_config()
    st.markdown(
        f"""
        <div style="background: #F7F8FA; border: 1px solid #E5E7EB; border-radius: 8px; padding: 0.65rem 0.85rem; font-size: 13px; color: #4B5563; margin-bottom: 1rem;">
            Global financial action ceiling: <b>₹{pol_cfg.ceiling:,}</b> &nbsp;•&nbsp; Minimum auto-confidence threshold: <b>{pol_cfg.min_auto_confidence:.2f}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

    current_modes = cfg_mgr.get_autonomy_modes()
    available_modes = list(cfg_mgr.autonomy_cfg.get("modes", {}).keys())
    locked_agents = cfg_mgr.autonomy_cfg.get("locked", ["fraud"])

    agent_cols = st.columns(3)
    for idx, (agent_name, mode_val) in enumerate(current_modes.items()):
        col = agent_cols[idx % 3]
        with col:
            is_locked = agent_name in locked_agents
            mode_cap = cfg_mgr.autonomy_cfg.get("modes", {}).get(mode_val, {}).get("auto_cap", 0)
            cap_label = f"₹{mode_cap:,}" if mode_cap > 0 else "human review only"

            st.markdown(f"**{agent_name}** ({cap_label})")
            new_mode = st.selectbox(
                "Autonomy level",
                available_modes,
                index=available_modes.index(mode_val) if mode_val in available_modes else 0,
                key=f"mode_sel_{agent_name}",
                disabled=is_locked,
                label_visibility="collapsed",
            )
            if new_mode != mode_val and not is_locked:
                try:
                    cfg_mgr.set_autonomy_mode(agent_name, new_mode, actor="A-2")
                    st.toast(f"{agent_name} updated to {new_mode}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to set mode: {exc}")

    st.write("")
    st.markdown("---")
    st.markdown("### Emergency kill-switches")
    st.write("Instantly pause autonomous disbursements per specialist agent or system-wide.")

    killswitches = cfg_mgr.get_killswitches()
    ks1, ks2, ks3 = st.columns(3)

    with ks1:
        all_paused = killswitches.get("all", False)
        if st.toggle("Pause all financial actions", value=all_paused, key="ks_toggle_all"):
            if not all_paused:
                cfg_mgr.set_killswitch("all", True, actor="A-2")
                st.toast("All autonomous actions paused.")
                st.rerun()
        else:
            if all_paused:
                cfg_mgr.set_killswitch("all", False, actor="A-2")
                st.toast("Autonomous actions resumed.")
                st.rerun()

    with ks2:
        pf_paused = killswitches.get("payment_failure", False)
        if st.toggle("Pause payment failure agent", value=pf_paused, key="ks_toggle_pf"):
            if not pf_paused:
                cfg_mgr.set_killswitch("payment_failure", True, actor="A-2")
                st.toast("Payment failure agent paused.")
                st.rerun()
        else:
            if pf_paused:
                cfg_mgr.set_killswitch("payment_failure", False, actor="A-2")
                st.toast("Payment failure agent resumed.")
                st.rerun()

    with ks3:
        rf_paused = killswitches.get("refund", False)
        if st.toggle("Pause refund specialist", value=rf_paused, key="ks_toggle_rf"):
            if not rf_paused:
                cfg_mgr.set_killswitch("refund", True, actor="A-2")
                st.toast("Refund specialist paused.")
                st.rerun()
        else:
            if rf_paused:
                cfg_mgr.set_killswitch("refund", False, actor="A-2")
                st.toast("Refund specialist resumed.")
                st.rerun()

    st.write("")
    st.markdown("### Configuration audit log")
    audits = query_core_all("SELECT * FROM config_audit ORDER BY id DESC LIMIT 15")
    if audits:
        df_aud = pd.DataFrame(audits)
        st.dataframe(
            df_aud[["id", "ts", "actor", "key", "old", "new"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Audit ID", width="small"),
                "ts": st.column_config.TextColumn("Timestamp", width="medium"),
                "actor": st.column_config.TextColumn("Actor", width="small"),
                "key": st.column_config.TextColumn("Key", width="medium"),
                "old": st.column_config.TextColumn("Previous", width="small"),
                "new": st.column_config.TextColumn("Updated", width="small"),
            },
        )
    else:
        st.caption("No configuration changes recorded.")
