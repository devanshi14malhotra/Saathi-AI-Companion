"""
Human Agent Co-Pilot & Escalations Workspace
Supervisor workspace for reviewing structured handoff packets and authorizing high-value actions.
"""

import json
import sys
from pathlib import Path
import pandas as pd
import streamlit as st

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, status_chip, id_chip, kv_list, confidence_panel
from streamlit_app.components.db_helper import (
    init_app_state,
    get_pending_approvals,
    get_all_escalations,
    run_async,
    query_core_all,
    crm_db,
)
from app.core.orchestrator import decide_approval

st.set_page_config(page_title="Agent Co-Pilot | Saathi", page_icon="🛡️", layout="wide")
inject_custom_css()
init_app_state()

page_header(
    title="Agent co-pilot",
    subtitle="Supervisor workspace for reviewing structured handoff packets and authorizing high-value financial actions",
)

# 1. Pending Approvals Queue
st.markdown("### Pending approvals")
pending = get_pending_approvals()

if not pending:
    st.info("No pending approval requests. Low-risk cases were autonomously resolved by Saathi.")
else:
    for idx, app_row in enumerate(pending):
        app_id = app_row.get("id")
        case_id = app_row.get("case_id")
        persona_id = app_row.get("persona_id", "Unknown")
        agent_name = app_row.get("agent", "payment_failure")
        intent = app_row.get("intent", "PAYMENT_QUERY")
        diagnosis = app_row.get("diagnosis", "GENERAL")
        rule_fired = app_row.get("rule_fired", "")
        created_at = str(app_row.get("created_at", ""))[:16]

        # Fetch CRM Handoff Packet
        hf_row = crm_db.query_one(
            "SELECT packet_json FROM handoffs WHERE case_id = ? ORDER BY id DESC LIMIT 1",
            (case_id,),
        )
        packet = json.loads(hf_row["packet_json"]) if (hf_row and hf_row.get("packet_json")) else {}

        # Proposed Action
        action_json = app_row.get("proposed_action_json") or "{}"
        try:
            action_data = json.loads(action_json)
        except Exception:
            action_data = {}

        action_name = action_data.get("name") or action_data.get("action", "action")
        action_args = action_data.get("args") or action_data
        action_amount = action_args.get("amount") or 0
        action_txn = action_args.get("txn_id") or ""

        # Proposed action plain sentence
        if action_name == "initiate_refund" and action_amount:
            proposed_sentence = f"Refund ₹{action_amount:,} for {action_txn} to customer {persona_id}"
        else:
            proposed_sentence = f"Execute {action_name} for customer {persona_id}"

        why_you = packet.get("why_you") or f"High-value financial action ({action_name}) exceeds autonomous policy cap."

        # Container for approval card (first expanded by default)
        with st.expander(
            f"{why_you} — ₹{action_amount:,} ({persona_id})",
            expanded=(idx == 0),
        ):
            # Card Header
            st.markdown(
                f'<div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #E5E7EB; padding-bottom: 0.5rem; margin-bottom: 0.75rem;">'
                f'<div><b>Approval {id_chip(app_id)}</b> &nbsp;•&nbsp; Case {id_chip(case_id)} &nbsp;•&nbsp; Customer {id_chip(persona_id)}</div>'
                f'<div>{status_chip("APPROVE")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            c_info, c_packet = st.columns([1, 1], gap="medium")

            with c_info:
                st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px;'>Case details</div>", unsafe_allow_html=True)
                kv_items = {
                    "Customer": persona_id,
                    "Specialist agent": agent_name,
                    "Intent": intent,
                    "Diagnosis": diagnosis,
                    "Policy rule": f"Rule {rule_fired}" if rule_fired else "Policy cap exceeded",
                    "Created at": created_at,
                }
                kv_list(kv_items)

                st.write("")
                st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px;'>Proposed action</div>", unsafe_allow_html=True)
                st.markdown(
                    f'<div style="background: #F7F8FA; border: 1px solid #E5E7EB; border-radius: 8px; padding: 0.65rem 0.85rem; font-size: 13px; color: #111827;">'
                    f'<b>{proposed_sentence}</b>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            with c_packet:
                st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px;'>Verified facts and checks</div>", unsafe_allow_html=True)

                # Verified facts
                facts = packet.get("verified_facts") or []
                if facts:
                    facts_html = "".join([f"<li style='margin-bottom: 2px;'>✓ {f}</li>" for f in facts])
                    st.markdown(f"<ul style='list-style: none; padding-left: 0; font-size: 13px; color: #027A48;'>{facts_html}</ul>", unsafe_allow_html=True)
                else:
                    st.caption("No pre-extracted facts available.")

                # Checks chips
                checks = packet.get("checks") or []
                if checks:
                    chips_html = " ".join([
                        f"<span style='display:inline-block; font-size: 11px; background:#F3F4F6; color:#374151; padding: 2px 6px; border-radius: 4px; margin-right: 4px; border: 1px solid #E5E7EB;'>✓ {c}</span>"
                        for c in checks
                    ])
                    st.markdown(f"<div style='margin-bottom: 8px;'>{chips_html}</div>", unsafe_allow_html=True)

                # Confidence
                conf = packet.get("confidence") or app_row.get("confidence") or 0.0
                st.markdown("<div style='font-size: 13px; font-weight: 600; margin-top: 6px; margin-bottom: 4px;'>Confidence breakdown</div>", unsafe_allow_html=True)
                confidence_panel(conf)

            # Raw packet in closed expander
            with st.expander("Raw handoff packet", expanded=False):
                st.json(packet)

            st.write("")

            # Action Buttons
            col_act1, col_act2, col_act3, _ = st.columns([1.2, 1.4, 1.2, 2])

            with col_act1:
                if st.button("Approve", key=f"btn_app_{app_id}", type="primary"):
                    try:
                        run_async(decide_approval(app_id, decision="APPROVED", actor="A-1"))
                        st.toast(f"Approval {app_id} authorized successfully.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Approval failed: {exc}")

            with col_act2:
                show_edit = st.popover("Edit and approve")
                with show_edit:
                    draft = packet.get("suggested_reply_draft") or ""
                    edited_text = st.text_area("Customer reply draft", value=draft, key=f"edit_draft_{app_id}")
                    if st.button("Submit edited approval", key=f"btn_edit_{app_id}", type="primary"):
                        try:
                            run_async(decide_approval(app_id, decision="EDITED", actor="A-1", edited_reply=edited_text))
                            st.toast(f"Approval {app_id} updated and authorized.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Failed to submit: {exc}")

            with col_act3:
                show_reject = st.popover("Reject")
                with show_reject:
                    st.markdown("<div style='font-size: 12px; color: #6B7280;'>Reason code is required for audit.</div>", unsafe_allow_html=True)
                    reason_code = st.selectbox(
                        "Rejection reason",
                        ["WRONG_AMOUNT", "DUPLICATE_RISK", "FRAUD_SUSPECTED", "POLICY_EXCEPTION", "OTHER"],
                        key=f"rej_code_{app_id}",
                    )
                    reason_text = st.text_input("Optional note", key=f"rej_note_{app_id}")
                    if st.button("Confirm rejection", key=f"btn_rej_submit_{app_id}"):
                        try:
                            run_async(decide_approval(
                                app_id,
                                decision="REJECTED",
                                actor="A-1",
                                reason_code=reason_code,
                                reason_text=reason_text or f"Rejected with {reason_code}",
                            ))
                            st.toast(f"Approval {app_id} rejected.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Rejection failed: {exc}")

st.write("")
st.markdown("---")

# 2. Historical Escalations Log
st.markdown("### Escalation and approval history")
escalations = get_all_escalations()
if escalations:
    df_esc = pd.DataFrame(escalations)
    if "id" in df_esc.columns:
        show_cols = [c for c in ["id", "persona_id", "agent", "intent", "rule_fired", "outcome", "created_at"] if c in df_esc.columns]
        st.dataframe(
            df_esc[show_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": st.column_config.TextColumn("Case ID", width="small"),
                "persona_id": st.column_config.TextColumn("Customer", width="small"),
                "agent": st.column_config.TextColumn("Specialist", width="small"),
                "intent": st.column_config.TextColumn("Intent", width="medium"),
                "rule_fired": st.column_config.TextColumn("Rule", width="small"),
                "outcome": st.column_config.TextColumn("Outcome", width="small"),
                "created_at": st.column_config.TextColumn("Created at", width="medium"),
            },
        )
else:
    st.caption("No historical escalations recorded.")
