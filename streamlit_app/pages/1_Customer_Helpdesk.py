"""
Customer Helpdesk & Support Workspace
Live customer dispute resolution with real-time financial actions,
calibrated confidence metrics, event timeline, and Sarvam AI voice integration.
"""

import sys
from pathlib import Path
import json
import streamlit as st

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, status_chip, id_chip, kv_list, confidence_panel, timeline
from streamlit_app.components.db_helper import (
    init_app_state,
    get_all_personas,
    get_user_transactions,
    run_async,
    handle_message,
    build_case_receipt,
    refunds_db,
    query_core_one,
)
from streamlit_app.components.sarvam import text_to_speech, speech_to_text, get_configured_keys

st.set_page_config(page_title="Customer Helpdesk | Saathi", page_icon="💬", layout="wide")
inject_custom_css()
init_app_state()

page_header(
    title="Customer helpdesk",
    subtitle="Interactive customer dispute resolution with real-time banking actions",
)

# 1. Customer Selection
all_personas = get_all_personas()
if not all_personas:
    st.info("No customer profiles found in database.")
    st.stop()

# Filter out admin/agent staff: Helpdesk is strictly for Customers (Consumers) and Merchants
eligible_personas = [
    p for p in all_personas
    if str(p.get("role", "")).lower() not in ("agent", "admin", "staff")
    and not str(p.get("id", "")).startswith("A-")
    and str(p.get("kyc_status", "")).upper() != "STAFF"
]
if not eligible_personas:
    eligible_personas = all_personas

# Simulation toggle
col_ctrl, _ = st.columns([1, 3])
with col_ctrl:
    show_sim = st.toggle("Show simulation users", value=False)

if not show_sim:
    visible_personas = [
        p for p in eligible_personas
        if not str(p.get("id", "")).startswith("U-3")
        and not p.get("hidden", False)
    ]
else:
    visible_personas = eligible_personas

if not visible_personas:
    visible_personas = eligible_personas

# Default to first consumer (U-101 if present)
default_idx = 0
for idx, p in enumerate(visible_personas):
    if p.get("id") == "U-101":
        default_idx = idx
        break

persona_map = {f"{p.get('name', 'User')} ({p.get('id')})": p for p in visible_personas}
persona_keys = list(persona_map.keys())

col_left, col_right = st.columns([3, 2], gap="large")

with col_left:
    selected_label = st.selectbox("Select customer or merchant account", persona_keys, index=min(default_idx, len(persona_keys) - 1))
    customer = persona_map[selected_label]
    pid = customer["id"]
    is_merchant = str(customer.get("role", "")).lower() == "merchant"

    # One-line profile
    p_name = customer.get("name", "Unknown")
    p_upi = customer.get("upi_id", "N/A")
    p_phone = customer.get("phone", "N/A")
    p_kyc = customer.get("kyc_status", "VERIFIED")
    p_role = customer.get("role", "consumer").capitalize()

    st.markdown(
        f'<div style="background: #F7F8FA; border: 1px solid #E5E7EB; border-radius: 8px; padding: 0.5rem 0.75rem; font-size: 13px; margin-bottom: 0.85rem;">'
        f'<b>{p_name}</b> &nbsp;{id_chip(pid)}&nbsp; • {p_role} • UPI: <code>{p_upi}</code> • Phone: {p_phone} • KYC: {status_chip(p_kyc)}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Fetch live data to generate real scenario chips
    txns = get_user_transactions(pid)
    user_refunds = refunds_db.query_all("SELECT * FROM refunds WHERE user_id = ? ORDER BY initiated_at DESC", (pid,)) if refunds_db else []
    user_settlements = refunds_db.query_all("SELECT * FROM settlements WHERE merchant_id = ? ORDER BY updated_at DESC", (pid,)) if (is_merchant and refunds_db) else []

    scenario_chips = []

    # 1. Failed & debited
    for t in txns:
        if t.get("status") == "FAILED" and t.get("debit_status") == "DEBITED":
            scenario_chips.append(f"My ₹{t['amount']:,} payment to {t.get('counterparty', 'merchant')} failed but money was debited")
            break

    # 2. Double debit
    amt_map = {}
    for t in txns:
        k = (t.get("amount"), t.get("counterparty"))
        amt_map[k] = amt_map.get(k, 0) + 1
    for (amt, cp), count in amt_map.items():
        if count >= 2:
            scenario_chips.append(f"I was debited twice for ₹{amt:,} at {cp}")
            break

    # 3. Pending transaction
    for t in txns:
        if t.get("status") == "PENDING":
            scenario_chips.append(f"My ₹{t['amount']:,} payment to {t.get('counterparty', 'merchant')} is stuck pending")
            break

    # 4. Refund status
    for rf in user_refunds:
        scenario_chips.append(f"Where is my refund for {rf['txn_id']}?")
        break

    # 5. Settlement
    for stl in user_settlements:
        scenario_chips.append(f"Where is my settlement {stl['id']}?")
        break

    # Always include human request
    scenario_chips.append("I want to talk to a human")

    st.markdown("<div style='font-size: 12px; font-weight: 500; color: #6B7280; margin-bottom: 4px;'>Suggested dispute scenarios:</div>", unsafe_allow_html=True)
    if scenario_chips:
        c_cols = st.columns(len(scenario_chips[:4]))
        for idx, text in enumerate(scenario_chips[:4]):
            short_lbl = text if len(text) <= 35 else f"{text[:32]}..."
            if c_cols[idx].button(short_lbl, key=f"chip_{idx}_{pid}", help=text):
                st.session_state["pending_chat_input"] = text
                st.rerun()
    else:
        st.caption("No recent transactions found for this customer.")

    # Voice Input (Collapsed Expander, NO warning banner)
    with st.expander("Voice input (optional)", expanded=False):
        st.write("Record speech or upload audio to transcribe via Sarvam AI.")
        v_col1, v_col2 = st.columns(2)
        with v_col1:
            mic_audio = st.audio_input("Record audio", key=f"mic_{pid}")
            if mic_audio is not None and st.button("Transcribe recording with saaras:v3", key=f"btn_mic_tx_{pid}"):
                with st.spinner("Transcribing..."):
                    tx_lang = "hi-IN" if customer.get("language") in ("hi", "hinglish") else "en-IN"
                    txt = speech_to_text(mic_audio.getvalue(), language_code=tx_lang)
                    if txt:
                        st.session_state["pending_chat_input"] = txt
                        st.rerun()
                    else:
                        st.error("Speech transcription was unable to process audio.")
        with v_col2:
            up_audio = st.file_uploader("Upload audio file", type=["wav", "mp3", "m4a"], key=f"up_{pid}")
            if up_audio is not None and st.button("Transcribe file with saaras:v3", key=f"btn_up_tx_{pid}"):
                with st.spinner("Transcribing..."):
                    tx_lang = "hi-IN" if customer.get("language") in ("hi", "hinglish") else "en-IN"
                    txt = speech_to_text(up_audio.read(), language_code=tx_lang)
                    if txt:
                        st.session_state["pending_chat_input"] = txt
                        st.rerun()
                    else:
                        st.error("Speech transcription was unable to process audio.")

    st.write("")

    # Chat Conversation History
    if f"chat_history_{pid}" not in st.session_state:
        st.session_state[f"chat_history_{pid}"] = []

    history = st.session_state[f"chat_history_{pid}"]

    # Render previous bubbles
    for chat_item in history:
        with st.chat_message(chat_item["role"]):
            st.write(chat_item["content"])

    # Chat input
    user_input = st.chat_input("Message Saathi regarding a payment dispute...")

    # If chip clicked, grab pending
    if "pending_chat_input" in st.session_state and st.session_state["pending_chat_input"]:
        user_input = st.session_state.pop("pending_chat_input")

    if user_input:
        # Add user message to history
        history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        with st.spinner("Investigating transaction and banking ledger..."):
            try:
                res = run_async(handle_message(persona_id=pid, text=user_input))
                st.session_state[f"active_case_{pid}"] = res

                # Assistant response from detail["messages"]
                msgs = res.get("messages", [])
                assistant_text = ""
                # Filter strictly for saathi / assistant messages (never echo user!)
                for m in reversed(msgs):
                    if m.get("role") in ("saathi", "assistant") or m.get("kind") in ("resolution", "saathi_text", "clarification"):
                        b = m.get("body", {})
                        if isinstance(b, dict) and b.get("text"):
                            assistant_text = b["text"]
                            break
                        elif isinstance(b, str) and b:
                            assistant_text = b
                            break

                # If no direct message on parent case, inspect child cases (multi-issue cases)
                if not assistant_text and res.get("children"):
                    from app.core.orchestrator import get_case_detail
                    for ch in res["children"]:
                        ch_detail = run_async(get_case_detail(ch["id"]))
                        for m in reversed(ch_detail.get("messages", [])):
                            if m.get("role") in ("saathi", "assistant"):
                                t = m.get("body", {}).get("text")
                                if t:
                                    assistant_text += (("\n\n" if assistant_text else "") + t)
                                    break

                # If still empty, check notify outbox
                if not assistant_text:
                    from app.mocks.notify.db import notify_db
                    outbox_msg = notify_db.query_one(
                        "SELECT message FROM outbox WHERE user_id = ? ORDER BY id DESC LIMIT 1", (pid,)
                    )
                    if outbox_msg and outbox_msg.get("message"):
                        assistant_text = outbox_msg["message"]

                if not assistant_text:
                    assistant_text = f"Case {res.get('id')} has been processed with outcome {res.get('outcome')}."

                history.append({"role": "assistant", "content": assistant_text})
                with st.chat_message("assistant"):
                    st.write(assistant_text)
                st.rerun()
            except Exception as exc:
                st.error(f"Error processing message: {exc}")


with col_right:
    st.markdown("### Case investigation")
    detail = st.session_state.get(f"active_case_{pid}")

    if not detail:
        st.caption("Select a customer and send a message to inspect autonomous investigation details.")
    else:
        case_id = detail.get("id", "N/A")
        outcome = detail.get("outcome", "UNKNOWN")
        agent = detail.get("agent", "general")
        intent = detail.get("intent", "UNKNOWN")
        diag = detail.get("diagnosis", "GENERAL")
        state = detail.get("state", "RESOLVED")
        rule_fired = detail.get("rule_fired") or ""

        # Case header with outcome chip
        st.markdown(
            f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">'
            f'<div><b>Case</b> {id_chip(case_id)}</div>'
            f'<div>{status_chip(outcome)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Policy line extraction from [POLICY] event
        events = detail.get("events", [])
        policy_line = "Verified against standard policy limits"
        for ev in events:
            if ev.get("badge") == "[POLICY]" or ev.get("type") == "POLICY":
                summary_text = ev.get("summary") or ""
                if summary_text:
                    policy_line = summary_text
                    break

        # Key-Value details
        kv_items = {
            "Specialist agent": agent,
            "Detected intent": intent,
            "Diagnosis": diag,
            "Policy rule": f"Rule {rule_fired}: {policy_line}" if rule_fired else policy_line,
        }
        kv_list(kv_items)
        st.write("")

        # Clarification handling
        latest_msg = detail["messages"][-1] if detail.get("messages") else {}
        if latest_msg.get("kind") == "clarification" or latest_msg.get("type") == "clarification":
            opts = latest_msg.get("body", {}).get("options") or latest_msg.get("options") or []
            if opts:
                st.markdown("<b>Select an option to clarify:</b>", unsafe_allow_html=True)
                for idx, opt in enumerate(opts):
                    opt_text = opt.get("label") or opt.get("text") or str(opt)
                    opt_txn = opt.get("txn_id") or f"opt_{idx}"
                    if st.button(opt_text, key=f"clarify_{case_id}_{pid}_{idx}_{opt_txn}"):
                        with st.spinner("Processing clarification..."):
                            c_res = run_async(handle_message(
                                persona_id=pid,
                                text=opt_text,
                                case_id=case_id,
                                selected_txn_id=opt_txn if opt_txn != f"opt_{idx}" else None,
                            ))
                            st.session_state[f"active_case_{pid}"] = c_res
                            st.rerun()

        # Approval pending state banner
        if state == "AWAITING_APPROVAL":
            st.warning("Waiting for human approval before execution.")
            try:
                from streamlit_app.app import p_copilot
                st.page_link(p_copilot, label="Open Co-Pilot to review and authorize approval")
            except Exception:
                st.info("Navigate to the Co-Pilot page to review and authorize this action.")

        st.write("")

        # Confidence Panel
        conf_data = None
        # Try fetching from confidence_log for full 4-signal breakdown
        conf_row = query_core_one("SELECT score, band, signals_json FROM confidence_log WHERE case_id = ?", (case_id,))
        if not conf_row and detail.get("children"):
            for ch in detail["children"]:
                ch_row = query_core_one("SELECT score, band, signals_json FROM confidence_log WHERE case_id = ?", (ch["id"],))
                if ch_row and ch_row.get("signals_json"):
                    conf_row = ch_row
                    break
        if conf_row and conf_row.get("signals_json"):
            try:
                sig_data = json.loads(conf_row["signals_json"])
                sig_data["score"] = conf_row.get("score")
                sig_data["band"] = conf_row.get("band")
                conf_data = sig_data
            except Exception:
                conf_data = {"score": conf_row.get("score"), "band": conf_row.get("band")}
        if not conf_data:
            conf_data = {"score": detail.get("confidence", 0.0), "band": detail.get("confidence_band", "MEDIUM")}

        st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px;'>Confidence calibration</div>", unsafe_allow_html=True)
        confidence_panel(conf_data)
        st.write("")

        # Timeline (ALL events)
        st.markdown("<div style='font-size: 13px; font-weight: 600; margin-bottom: 4px;'>Audit timeline</div>", unsafe_allow_html=True)
        timeline(events)
        st.write("")

        # Voice Synthesis for Assistant Response
        msgs = detail.get("messages", [])
        last_assistant_msg = ""
        for m in reversed(msgs):
            b = m.get("body", {})
            if isinstance(b, dict) and b.get("text"):
                last_assistant_msg = b["text"]
                break
        if last_assistant_msg:
            with st.expander("Audio playback (bulbul:v3)", expanded=False):
                # Derive language from case language
                case_lang = str(detail.get("language") or customer.get("language") or "en").lower()
                tts_lang = "hi-IN" if case_lang in ("hi", "hinglish") else "en-IN"
                if st.button("Synthesize response voice", key=f"tts_{case_id}"):
                    with st.spinner("Synthesizing audio..."):
                        audio_data = text_to_speech(last_assistant_msg, language_code=tts_lang, speaker="priya")
                        if audio_data:
                            st.audio(audio_data, format="audio/wav")
                        else:
                            st.caption("Sarvam voice synthesis offline or unavailable.")

        # Collapsed Expanders
        with st.expander("Customer receipt", expanded=False):
            try:
                receipt = build_case_receipt(case_id)
                for step in receipt.get("steps", []):
                    st.markdown(
                        f"""
                        <div style="padding: 4px 0; border-bottom: 1px solid #E5E7EB; font-size: 12px;">
                            <span style="color: #6B7280;">{step.get('ts', '')}</span> — <b>{step.get('line', '')}</b>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            except Exception:
                st.caption("Receipt unavailable for this case.")

        with st.expander("Entity extraction", expanded=False):
            st.json(detail.get("extraction", {}))
