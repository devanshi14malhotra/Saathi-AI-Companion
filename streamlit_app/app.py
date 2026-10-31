"""
Saathi v6.0 — Autonomous AI Customer-Service Teammate
Main Application Dashboard & Navigation Router
"""

import os
import sys
from typing import Any
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import streamlit as st

# Ensure repository root and backend are on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env", override=False)
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

# If Sarvam key is configured and LLM_PROVIDER is not explicitly set, default to sarvam
if os.environ.get("SARVAM_API_KEY") and not os.environ.get("LLM_PROVIDER"):
    os.environ["LLM_PROVIDER"] = "sarvam"

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, kpi
from streamlit_app.components.db_helper import init_app_state, get_live_metrics, query_core_all

st.set_page_config(
    page_title="Saathi | Autonomous Operations",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()
init_app_state()


def render_overview() -> None:
    """Renders the executive operations overview dashboard."""
    page_header(
        title="Operations overview",
        subtitle="Autonomous customer-service operations, dispute resolution, and banking telemetry",
    )

    metrics = get_live_metrics()

    # KPI Strip
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        kpi("Total cases handled", f"{metrics['total_cases']:,}", "Across all banking rails")
    with k2:
        kpi("Auto-resolution rate", f"{metrics['auto_rate']}%", f"{metrics['auto_resolved']} resolved autonomously")
    with k3:
        kpi("Human escalations", f"{metrics['escalated']:,}", "Supervisor reviews")
    with k4:
        kpi("Refunds issued", f"₹{metrics['refund_amount']:,}", f"{metrics['refund_count']} disbursements")
    with k5:
        kpi("RBI TAT compensation", f"₹{metrics['comp_amount']:,}", f"{metrics['comp_count']} delay claims")

    st.write("")
    st.write("")

    # Recent Cases Stream & Outcome Distribution
    st.markdown("### Recent cases")
    recent_cases = query_core_all(
        """
        SELECT id, persona_id, agent, intent, outcome, confidence, created_at
        FROM cases
        ORDER BY id DESC
        LIMIT 10
        """
    )

    if recent_cases:
        df = pd.DataFrame(recent_cases)

        def fmt_time(ts_str: Any) -> str:
            if not ts_str:
                return "—"
            try:
                # Handle ISO timestamps like 2026-10-31T06:28:15.123456
                clean_ts = str(ts_str).replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_ts)
                return dt.strftime("%d %b, %H:%M")
            except Exception:
                return str(ts_str)[:16]

        df["formatted_time"] = df["created_at"].apply(fmt_time)

        st.dataframe(
            df[["id", "persona_id", "agent", "intent", "outcome", "confidence", "formatted_time"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Case ID", width="small"),
                "persona_id": st.column_config.TextColumn("Customer", width="small"),
                "agent": st.column_config.TextColumn("Specialist", width="medium"),
                "intent": st.column_config.TextColumn("Intent", width="medium"),
                "outcome": st.column_config.TextColumn("Outcome", width="small"),
                "confidence": st.column_config.ProgressColumn("Confidence", min_value=0.0, max_value=1.0, format="%.2f"),
                "formatted_time": st.column_config.TextColumn("Timestamp", width="medium"),
            },
        )
    else:
        st.caption("No cases processed yet.")

    st.write("")

    # Distribution Chart
    dist_rows = query_core_all(
        """
        SELECT agent, outcome, COUNT(*) as count
        FROM cases
        GROUP BY agent, outcome
        """
    )
    if dist_rows:
        st.markdown("### Outcomes by specialist agent")
        df_dist = pd.DataFrame(dist_rows)
        pivot_df = df_dist.pivot(index="agent", columns="outcome", values="count").fillna(0)
        st.bar_chart(pivot_df)

    st.write("")
    st.markdown("### Workspace shortcuts")
    st.page_link(p_helpdesk, label="Customer Helpdesk — Resolve disputes and test multilingual voice queries")
    st.page_link(p_copilot, label="Agent Co-Pilot — Authorize high-value refund escalations and review handoff packets")
    st.page_link(p_ledger, label="Transactions Ledger — Inspect live UPI transactions, merchant settlements, and refunds")
    st.page_link(p_operations, label="Operations — Monitor bank gateway outages, time-travel TAT claims, and kill-switches")
    st.page_link(p_analytics, label="Analytics — View audit events, agent performance, and notification outbox")
    st.page_link(p_settings, label="Settings — Configure credentials and system provider")


# Navigation Routing
p_overview = st.Page(render_overview, title="Overview", icon=":material/dashboard:", default=True)
p_helpdesk = st.Page("pages/1_Customer_Helpdesk.py", title="Helpdesk", icon=":material/support_agent:")
p_copilot = st.Page("pages/2_Agent_CoPilot.py", title="Co-Pilot", icon=":material/shield_person:")
p_ledger = st.Page("pages/3_Transactions_Ledger.py", title="Ledger", icon=":material/receipt_long:")
p_operations = st.Page("pages/4_Operations.py", title="Operations", icon=":material/tune:")
p_analytics = st.Page("pages/5_Analytics.py", title="Analytics", icon=":material/monitoring:")
p_settings = st.Page("pages/6_Settings.py", title="Settings", icon=":material/settings:")

nav = st.navigation({
    "Overview": [p_overview],
    "Customer": [p_helpdesk],
    "Operations": [p_copilot, p_ledger, p_operations],
    "System": [p_analytics, p_settings],
})

nav.run()
