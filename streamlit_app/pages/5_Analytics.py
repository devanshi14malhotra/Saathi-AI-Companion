"""
Analytics & Audit Telemetry Workspace
Real-time operational metrics, transparent case audit trail, specialist agent performance,
and notification outbox logs computed directly from SQLite tables.
"""

from datetime import datetime
import statistics
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, kpi, id_chip, status_chip
from streamlit_app.components.db_helper import (
    init_app_state,
    get_live_metrics,
    query_core_all,
    notify_db,
)

st.set_page_config(page_title="Analytics | Saathi", page_icon="📊", layout="wide")
inject_custom_css()
init_app_state()

page_header(
    title="Analytics",
    subtitle="Operational telemetry, case audit events, agent performance, and notification outbox",
)

metrics = get_live_metrics()

# Compute real median resolution time from cases
time_rows = query_core_all(
    "SELECT created_at, closed_at FROM cases WHERE created_at IS NOT NULL AND closed_at IS NOT NULL"
)
durations = []
for r in time_rows:
    try:
        t0 = datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(str(r["closed_at"]).replace("Z", "+00:00"))
        delta = (t1 - t0).total_seconds()
        if delta >= 0:
            durations.append(delta)
    except Exception:
        pass

median_str = f"Median resolution {statistics.median(durations):.1f}s" if durations else ""

# KPI Row
m1, m2, m3, m4 = st.columns(4)
with m1:
    kpi("Total disputes", f"{metrics['total_cases']:,}", "Across all banking rails")
with m2:
    kpi("Automation rate", f"{metrics['auto_rate']}%", median_str if median_str else f"{metrics['auto_resolved']} resolved autonomously")
with m3:
    kpi("Escalations", f"{metrics['escalated']:,}", "Supervisor reviews")
with m4:
    kpi("Disbursed refunds", f"₹{metrics['refund_amount']:,}", f"{metrics['refund_count']} transactions")

st.write("")

tab_events, tab_agents, tab_notify = st.tabs([
    "Case events",
    "Agents",
    "Notifications",
])

# ---------------------------------------------------------
# TAB 1: CASE EVENTS (LAST 200)
# ---------------------------------------------------------
with tab_events:
    st.markdown("### Transparent decision and event log")
    events = query_core_all(
        """
        SELECT id, case_id, seq, badge, type, summary, ts
        FROM case_events
        ORDER BY id DESC
        LIMIT 200
        """
    )
    if events:
        df_ev = pd.DataFrame(events)
        st.dataframe(
            df_ev[["id", "case_id", "badge", "type", "summary", "ts"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Event ID", width="small"),
                "case_id": st.column_config.TextColumn("Case ID", width="small"),
                "badge": st.column_config.TextColumn("Badge", width="small"),
                "type": st.column_config.TextColumn("Type", width="small"),
                "summary": st.column_config.TextColumn("Summary", width="large"),
                "ts": st.column_config.TextColumn("Timestamp", width="medium"),
            },
        )
    else:
        st.info("No case events recorded yet.")


# ---------------------------------------------------------
# TAB 2: AGENTS
# ---------------------------------------------------------
with tab_agents:
    st.markdown("### Specialist agent performance")
    agent_stats = query_core_all(
        """
        SELECT agent,
               COUNT(*) as total_cases,
               SUM(CASE WHEN outcome = 'AUTO' THEN 1 ELSE 0 END) as auto_resolved,
               SUM(CASE WHEN outcome IN ('APPROVE', 'ESCALATE') THEN 1 ELSE 0 END) as escalated,
               ROUND(AVG(confidence), 2) as avg_confidence
        FROM cases
        GROUP BY agent
        ORDER BY total_cases DESC
        """
    )
    if agent_stats:
        df_ag = pd.DataFrame(agent_stats)
        st.dataframe(
            df_ag,
            use_container_width=True,
            hide_index=True,
            column_config={
                "agent": st.column_config.TextColumn("Specialist Agent", width="medium"),
                "total_cases": st.column_config.NumberColumn("Total Cases"),
                "auto_resolved": st.column_config.NumberColumn("Auto Resolved"),
                "escalated": st.column_config.NumberColumn("Escalated"),
                "avg_confidence": st.column_config.ProgressColumn("Avg Confidence", min_value=0.0, max_value=1.0, format="%.2f"),
            },
        )

        st.write("")
        st.markdown("### Case volume by agent")
        chart_data = df_ag.set_index("agent")[["auto_resolved", "escalated"]]
        st.bar_chart(chart_data)
    else:
        st.info("No agent performance data available yet.")


# ---------------------------------------------------------
# TAB 3: NOTIFICATIONS (NOTIFY OUTBOX)
# ---------------------------------------------------------
with tab_notify:
    st.markdown("### Notification outbox")
    st.write("Customer notifications dispatched by the notification service.")

    outbox_rows = notify_db.query_all("SELECT * FROM outbox ORDER BY id DESC LIMIT 100") if notify_db else []
    if outbox_rows:
        df_out = pd.DataFrame(outbox_rows)
        cols_out = ["id", "user_id", "channel", "message", "case_id", "created_at"]
        valid_out = [c for c in cols_out if c in df_out.columns]

        st.dataframe(
            df_out[valid_out],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("ID", width="small"),
                "user_id": st.column_config.TextColumn("Customer", width="small"),
                "channel": st.column_config.TextColumn("Channel", width="small"),
                "message": st.column_config.TextColumn("Message content", width="large"),
                "case_id": st.column_config.TextColumn("Linked case", width="small"),
                "created_at": st.column_config.TextColumn("Dispatched at", width="medium"),
            },
        )
    else:
        st.info("No dispatched notifications in outbox.")
