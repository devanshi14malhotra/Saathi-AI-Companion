"""
Human Agent Co-Pilot & Supervisor Inbox
Provides structured Handoff Packets, audit trails, and 1-Click human decisions
for high-value or sensitive customer disputes escalated by Saathi.
"""

import streamlit as st
import json
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css, render_header
from streamlit_app.components.db_helper import (
    init_app_state,
    get_pending_approvals,
    get_all_escalations,
    resolve_approval,
    query_core_one,
)

st.set_page_config(page_title="Agent Co-Pilot | Paytm Saathi", page_icon="🛡️", layout="wide")
inject_custom_css()
init_app_state()

render_header(
    title="Human Agent Co-Pilot & Escalations Inbox",
    subtitle="Supervisor workspace for reviewing AI Handoff Packets and authorizing high-value financial actions",
    badge="Supervisor View",
)

# 1. Pending Approvals Queue
st.subheader("📬 Pending Action Authorization Queue")
pending = get_pending_approvals()

if not pending:
    st.success("🎉 No pending approval requests! All low-risk cases were auto-resolved by Saathi AI.")
else:
    st.info(f"⚠️ **{len(pending)} pending action(s)** require human authorization before financial execution.")

    for app in pending:
        app_id = app.get("id")
        case_id = app.get("case_id")
        action_json = app.get("proposed_action_json") or "{}"
        action_data = json.loads(action_json)
        action_name = action_data.get("name") or action_data.get("action", "unknown_action")
        action_args = action_data.get("args") or action_data

        with st.container():
            st.markdown(
                f"""
                <div style="background: #FFFFFF; border: 2px solid #5379AE; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.25rem; box-shadow: 0 4px 12px rgba(38,43,64,0.06);">
                    <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #A8C4EC; padding-bottom: 0.5rem; margin-bottom: 0.75rem;">
                        <div>
                            <span style="font-weight: 700; color: #06457F; font-size: 1.1rem;">Approval Request: <code>{app_id}</code></span>
                            &nbsp;|&nbsp; Case: <code>{case_id}</code>
                        </div>
                        <span class="status-pill pill-pending">Action Required: {action_name}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            c_info, c_packet = st.columns([1, 2])

            with c_info:
                st.write("**Case Details:**")
                st.write(f"- **Customer:** `{app.get('persona_id')}`")
                st.write(f"- **Specialist Agent:** `{app.get('agent')}`")
                st.write(f"- **Intent:** `{app.get('intent')}`")
                st.write(f"- **Diagnosis:** `{app.get('diagnosis')}`")
                st.write(f"- **Confidence:** `{float(app.get('confidence') or 0):.2f}`")
                st.write(f"- **Escalation Reason:** `{app.get('rule_fired') or 'Policy Cap Exceeded'}`")

                st.write("**Proposed Action Details:**")
                st.json(action_args)

            with c_packet:
                st.write("**Structured Handoff Packet:**")
                # Fetch CRM handoff packet if available
                from app.mocks.crm.db import crm_db
                hf_row = crm_db.query_one("SELECT packet_json FROM handoffs WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,))
                if hf_row and hf_row.get("packet_json"):
                    packet = json.loads(hf_row["packet_json"])
                    st.json({
                        "summary": packet.get("english_summary"),
                        "why_escalated": packet.get("rule_fired_text"),
                        "verified_facts": packet.get("verified_facts"),
                        "suggested_action": packet.get("suggested_action"),
                        "confidence_breakdown": packet.get("confidence"),
                    })
                else:
                    st.caption("Standard handoff packet generated from core case record.")

            # Decision Buttons
            btn_col1, btn_col2, btn_spacer = st.columns([1, 1, 3])
            with btn_col1:
                if st.button(f"✅ Authorize & Execute", key=f"app_{app_id}", type="primary"):
                    if resolve_approval(app_id, "APPROVE", reviewer="Supervisor"):
                        st.success(f"Action {action_name} authorized and executed in refunds/ledger DB!")
                        st.rerun()

            with btn_col2:
                if st.button(f"❌ Reject Action", key=f"rej_{app_id}"):
                    if resolve_approval(app_id, "REJECT", reviewer="Supervisor"):
                        st.warning(f"Action {action_name} was rejected.")
                        st.rerun()

st.markdown("---")

# 2. Historical Escalations Log
st.subheader("📜 All Escalated Cases & Handoff History")
escalations = get_all_escalations()
if escalations:
    import pandas as pd
    df_esc = pd.DataFrame(escalations)[["id", "persona_id", "agent", "intent", "rule_fired", "outcome", "created_at"]]
    st.dataframe(df_esc, use_container_width=True, hide_index=True)
else:
    st.caption("No escalated cases recorded yet.")

