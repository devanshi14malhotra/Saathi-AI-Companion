"""
Paytm Saathi - Autonomous AI Teammate
Main Application Dashboard & Executive Command Center
"""

import streamlit as st
import os
import sys
from pathlib import Path

# Ensure paths
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css, render_header, render_metric_card
from streamlit_app.components.db_helper import init_app_state, get_live_metrics, query_core_all

st.set_page_config(
    page_title="Paytm Saathi | Autonomous AI Teammate",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
init_app_state()

render_header(
    title="Paytm Saathi — Autonomous AI Teammate",
    subtitle="End-to-End Customer Service & Financial Dispute Automation Engine",
    badge="Production Live",
)

metrics = get_live_metrics()

# Top KPI Metric Row
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    render_metric_card("Total Cases Handled", f"{metrics['total_cases']}", "Across all rails & UPI")
with m2:
    render_metric_card("Auto-Resolution Rate", f"{metrics['auto_rate']}%", f"{metrics['auto_resolved']} resolved without human")
with m3:
    render_metric_card("Human Escalations", f"{metrics['escalated']}", "Amber lane handoffs")
with m4:
    render_metric_card("Refunds Issued", f"₹{metrics['refund_amount']:,}", f"{metrics['refund_count']} automated refunds")
with m5:
    render_metric_card("RBI TAT Compensation", f"₹{metrics['comp_amount']:,}", f"{metrics['comp_count']} delay claims credited")

st.markdown("---")

# Quick Navigation Hub
st.subheader("🚀 Teammate Workspaces & Operational Portals")
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown(
        """
        <div style="background: #F8FAFD; border: 1px solid #A8C4EC; border-radius: 10px; padding: 1.25rem; height: 100%;">
            <h4 style="color: #06457F; margin-top:0;">💬 1. Customer Support & Voice</h4>
            <p style="color: #2C444C; font-size: 0.9rem;">
                Live customer support simulator. Test queries in English, Hindi, or Hinglish with text or <b>Sarvam AI Voice (STT & TTS)</b>.
                Inspect real-time resolution cards (Found / Did / Next) and customer action receipts.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c2:
    st.markdown(
        """
        <div style="background: #F8FAFD; border: 1px solid #A8C4EC; border-radius: 10px; padding: 1.25rem; height: 100%;">
            <h4 style="color: #06457F; margin-top:0;">🛡️ 2. Human Agent Co-Pilot</h4>
            <p style="color: #2C444C; font-size: 0.9rem;">
                Supervisor and support lead workspace. View amber-lane escalated cases, inspect structured <b>Handoff Packets</b>, 
                and execute <b>1-Click Approvals</b> for high-value refunds (>₹2,000) or complex disputes.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c3:
    st.markdown(
        """
        <div style="background: #F8FAFD; border: 1px solid #A8C4EC; border-radius: 10px; padding: 1.25rem; height: 100%;">
            <h4 style="color: #06457F; margin-top:0;">💳 3. Live Transactions & Ledger</h4>
            <p style="color: #2C444C; font-size: 0.9rem;">
                Real-time ledger explorer across UPI, BillPay, and Merchant rails. Track transaction states, debit vs merchant credit status, 
                and inspect live linked refunds in the refunds microservice.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")
c4, c5, c6 = st.columns(3)

with c4:
    st.markdown(
        """
        <div style="background: #F8FAFD; border: 1px solid #A8C4EC; border-radius: 10px; padding: 1.25rem; height: 100%;">
            <h4 style="color: #06457F; margin-top:0;">⚡ 4. Operations & Outage War-Room</h4>
            <p style="color: #2C444C; font-size: 0.9rem;">
                Bank outage incident management (HDFC/SBI spike detection & auto-deflection), <b>Time Travel machine (+24h/+72h)</b> 
                to trigger RBI TAT compensation claims, phantom-write chaos injection, and safety kill-switches.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c5:
    st.markdown(
        """
        <div style="background: #F8FAFD; border: 1px solid #A8C4EC; border-radius: 10px; padding: 1.25rem; height: 100%;">
            <h4 style="color: #06457F; margin-top:0;">📊 5. Analytics & Live Audit Trail</h4>
            <p style="color: #2C444C; font-size: 0.9rem;">
                Transparent audit log of every decision, tool invocation, and verification check. 
                Inspect resolution speed distribution and policy threshold performance.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c6:
    st.markdown(
        """
        <div style="background: #F8FAFD; border: 1px solid #A8C4EC; border-radius: 10px; padding: 1.25rem; height: 100%;">
            <h4 style="color: #06457F; margin-top:0;">⚙️ 6. System & Model Health</h4>
            <p style="color: #2C444C; font-size: 0.9rem;">
                Monitors credentials loaded from your local <code>.env</code> file (Dual Account failover with 1,200 credits). 
                Test live API health, switch between Sarvam-30B LLM and local offline stub, and test voice synthesis.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("---")

# Recent Live System Activity
st.subheader("📋 Recent Real-Time Case Stream")
recent_cases = query_core_all(
    """
    SELECT id, persona_id, agent, intent, outcome, confidence, created_at
    FROM cases
    ORDER BY id DESC
    LIMIT 10
    """
)

if recent_cases:
    import pandas as pd
    df = pd.DataFrame(recent_cases)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.TextColumn("Case ID", width="small"),
            "persona_id": st.column_config.TextColumn("Customer ID", width="small"),
            "agent": st.column_config.TextColumn("Specialist Agent", width="medium"),
            "intent": st.column_config.TextColumn("Extracted Intent", width="medium"),
            "outcome": st.column_config.TextColumn("Decision Outcome", width="small"),
            "confidence": st.column_config.ProgressColumn("Confidence", min_value=0.0, max_value=1.0, format="%.2f"),
            "created_at": st.column_config.TextColumn("Created At", width="medium"),
        },
    )
else:
    st.info("No cases processed yet. Navigate to '1_💬_Customer_Helpdesk' to test live queries!")
