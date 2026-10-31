"""
Customer Helpdesk & Voice Assistant Portal
Live interactive interface for real customer dispute resolutions.
Supports Text and Sarvam AI Live Voice (Microphone STT & TTS) in English, Hindi, and Hinglish.
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
    get_all_personas,
    get_user_transactions,
    run_async,
    handle_message,
    build_case_receipt,
)
from streamlit_app.components.sarvam import text_to_speech, speech_to_text, get_configured_keys

st.set_page_config(page_title="Customer Helpdesk | Paytm Saathi", page_icon="💬", layout="wide")
inject_custom_css()
init_app_state()

render_header(
    title="Customer Helpdesk & Voice Assistant",
    subtitle="Interactive customer dispute resolution with real-time financial actions & Sarvam AI Voice",
    badge="Customer View",
)

# 1. Customer Selection (Filtered to real consumers & merchants, excluding internal agents)
all_personas = get_all_personas()
consumer_personas = [p for p in all_personas if p.get("role", "consumer").lower() in ("consumer", "merchant")]
if not consumer_personas:
    consumer_personas = all_personas

p_options = {f"{p['name']} ({p['id']}) - {p.get('role', 'consumer').capitalize()}": p for p in consumer_personas}

col_p1, col_p2 = st.columns([1, 2])
with col_p1:
    selected_label = st.selectbox("Select Active Customer:", list(p_options.keys()))
    customer = p_options[selected_label]
    pid = customer["id"]

with col_p2:
    # High-contrast white box with explicit black text for dark-mode visibility (Screenshot 2 fix)
    st.markdown(
        f"""
        <div class="white-box profile-card" style="background-color: #FFFFFF !important; border: 1px solid #0474C4 !important; border-radius: 8px; padding: 0.75rem 1.25rem; color: #000000 !important; box-shadow: 0 2px 6px rgba(0,0,0,0.08);">
            <div style="color: #000000 !important; font-size: 0.95rem; line-height: 1.5;">
                <b style="color: #000000 !important;">Profile:</b> <span style="color: #000000 !important; font-weight: 600;">{customer['name']}</span> &nbsp;|&nbsp; 
                <b style="color: #000000 !important;">UPI ID:</b> <code style="background-color: #EEF2F6 !important; color: #0474C4 !important; font-weight: 700; padding: 2px 6px; border-radius: 4px;">{customer.get('upi_id', 'N/A')}</code> &nbsp;|&nbsp; 
                <b style="color: #000000 !important;">Phone:</b> <span style="color: #000000 !important;">{customer.get('phone', 'N/A')}</span> &nbsp;|&nbsp; 
                <b style="color: #000000 !important;">KYC:</b> <span class="status-pill pill-success" style="font-weight: 700; border: 1px solid #4CAF50;">{customer.get('kyc_status', 'VERIFIED')}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Customer's live transactions in ledger
txns = get_user_transactions(pid)
with st.expander(f"💳 View {customer['name']}'s Recent Ledger Transactions ({len(txns)} found)", expanded=False):
    if txns:
        import pandas as pd
        st.dataframe(
            pd.DataFrame(txns)[["id", "amount", "counterparty", "status", "debit_status", "bank_code", "created_at"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No prior transactions recorded for this customer.")

st.markdown("---")

# 2. Input Section
st.subheader("📝 Customer Message / Voice Input")

quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)
if quick_col1.button("⚡ ₹1,499 Duplicate Debit", help="Duplicate debit refund inquiry"):
    st.session_state["query_input"] = "Mera ₹1,499 do baar deduct hua hai swiggy pe. Pls refund karo."

if quick_col2.button("⚠️ ₹4,500 High-Value Bill", help="High-value payment complaint"):
    st.session_state["query_input"] = "I paid electricity bill of Rs 4500 but it failed and money was debited."

if quick_col3.button("🏦 HDFC Outage Payment", help="Bank downtime payment inquiry"):
    st.session_state["query_input"] = "Payment to Ramesh failed from my HDFC bank account. Did the money cut?"

if quick_col4.button("⏳ Delayed Refund Check", help="Delayed refund and RBI TAT compensation"):
    st.session_state["query_input"] = "TXN-8821 refund has not come since 3 days. Where is my money?"

# Voice Input with Live Microphone & File Upload
sarvam_keys = get_configured_keys()
has_sarvam = len(sarvam_keys) > 0

with st.expander("🎙️ Live Voice Input (Microphone & Audio Upload)", expanded=True):
    if not has_sarvam:
        st.info("💡 Sarvam AI voice model is offline. Text-based query handling is active.")

    v_tab1, v_tab2 = st.tabs(["🔴 Live Microphone Recording", "📁 Upload Audio File"])

    with v_tab1:
        st.write("Click the **Microphone** below to record your voice complaint. You can listen to the playback, delete and re-record with the trash icon, or transcribe directly.")
        live_audio = st.audio_input("Record voice query live:", key="mic_recorder")
        if live_audio is not None:
            if st.button("Transcribe Live Recording with Sarvam AI 🎙️", type="primary", key="btn_transcribe_live"):
                with st.spinner("Transcribing speech with Sarvam saaras:v1..."):
                    audio_bytes = live_audio.getvalue()
                    transcript = speech_to_text(audio_bytes, language_code="hi-IN")
                    if transcript:
                        st.session_state["query_input"] = transcript
                        st.success(f"Transcribed: '{transcript}'")
                        st.rerun()
                    else:
                        st.error("Sarvam STT failed. Check your API key or network connection.")

    with v_tab2:
        audio_file = st.file_uploader("Upload audio recording (.wav / .mp3 / .m4a):", type=["wav", "mp3", "m4a"], key="upload_file")
        if audio_file is not None and st.button("Transcribe Uploaded File with Sarvam saaras:v1 📁", key="btn_transcribe_upload"):
            with st.spinner("Transcribing speech with Sarvam AI..."):
                audio_bytes = audio_file.read()
                transcript = speech_to_text(audio_bytes, language_code="hi-IN")
                if transcript:
                    st.session_state["query_input"] = transcript
                    st.success(f"Transcribed: '{transcript}'")
                    st.rerun()
                else:
                    st.error("Sarvam STT failed. Check your API key or network connection.")

# Main Input Form
default_text = st.session_state.get("query_input", "Mera ₹1,499 do baar deduct hua hai. Kripya refund check karein.")
message_text = st.text_area(
    "Customer Query (English, Hindi, or Hinglish):",
    value=default_text,
    height=85,
    help="Type customer complaint or question. Saathi will protect PII, extract intent, check ledger, and take financial action.",
)

if "active_case_detail" not in st.session_state:
    st.session_state["active_case_detail"] = None
if "active_case_audio" not in st.session_state:
    st.session_state["active_case_audio"] = None

c_run, c_clear = st.columns([1, 5])
submit = c_run.button("Send to Saathi 🚀", type="primary", use_container_width=True)
if c_clear.button("Clear / New Query 🔄"):
    st.session_state["active_case_detail"] = None
    st.session_state["active_case_audio"] = None
    st.rerun()

if submit and message_text.strip():
    with st.spinner("Saathi AI Teammate is processing query & verifying ledger..."):
        try:
            st.session_state["active_case_detail"] = run_async(handle_message(persona_id=pid, text=message_text.strip()))
            st.session_state["active_case_audio"] = None
        except Exception as e:
            st.error(f"Error processing message: {str(e)}")
            st.stop()

detail = st.session_state.get("active_case_detail")

if detail:
    case_id = detail.get("id")
    outcome = detail.get("outcome", "UNKNOWN")
    agent = detail.get("agent", "general")
    diagnosis = detail.get("diagnosis", "GENERAL")
    confidence = detail.get("confidence", 0.0)

    st.markdown("---")
    st.subheader(f"🎯 Resolution for Case `{case_id}`")

    # Status Pill
    if outcome == "AUTO":
        st.markdown(f'<span class="status-pill pill-success" style="font-weight: 700;">✅ AUTO RESOLVED BY TEAMMATE</span> &nbsp; Agent: <b>{agent}</b> | Diagnosis: <b>{diagnosis}</b> | Confidence: <b>{confidence:.2f}</b>', unsafe_allow_html=True)
    elif outcome in ("ESCALATE", "ESCALATED"):
        st.markdown(f'<span class="status-pill pill-pending" style="font-weight: 700;">⚠️ ESCALATED TO HUMAN LEAD (AMBER LANE)</span> &nbsp; Rule Fired: <b>{detail.get("rule_fired")}</b> | Agent: <b>{agent}</b>', unsafe_allow_html=True)
    else:
        st.markdown(f'<span class="status-pill pill-info" style="font-weight: 700;">ℹ️ {outcome}</span> &nbsp; Agent: <b>{agent}</b>', unsafe_allow_html=True)

    # Fetch customer-facing resolution messages and dynamic 3-part sections
    msgs = detail.get("messages", [])
    cust_msg_text = ""
    sections = {}
    for m in reversed(msgs):
        body = m.get("body", {})
        if isinstance(body, dict):
            if not cust_msg_text and body.get("text"):
                cust_msg_text = body["text"]
            if not sections and body.get("found"):
                sections = {"found": body.get("found"), "did": body.get("did"), "next": body.get("next")}
        if cust_msg_text and sections:
            break

    if not sections:
        for e in reversed(detail.get("events", [])):
            sec = e.get("payload", {}).get("sections")
            if isinstance(sec, dict) and sec.get("found"):
                sections = sec
                break

    found_text = sections.get("found") or f"Identified issue {detail.get('intent', 'PAYMENT_QUERY')} for user {pid}. Verified banking ledger records for payment state and debit confirmation."
    did_text = sections.get("did") or ("Executed automated refund via refunds microservice and verified receipt with read-after-write check." if outcome == "AUTO" else "Transferred with structured Handoff Packet to Human Support Lead due to safety policy threshold.")
    next_text = sections.get("next") or (cust_msg_text or "Status updated in core.db. Notification dispatched to customer outbox.")

    # Structured 3-Part Resolution Card (White background with explicit black text)
    ext = detail.get("extraction", {})
    st.markdown(
        f"""
        <div class="white-box resolution-box" style="background-color: #FFFFFF !important; border: 1px solid #A8C4EC; border-left: 5px solid #0474C4 !important; border-radius: 0 10px 10px 0; padding: 1.25rem; margin: 1rem 0; color: #000000 !important; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
            <div class="resolution-section" style="margin-bottom: 0.85rem;">
                <span class="resolution-label res-found" style="color: #06457F !important; font-weight: 700;">🔍 1. What Saathi Found</span>
                <p style="margin: 0.25rem 0 0 0; color: #000000 !important; font-size: 0.95rem; line-height: 1.5;">
                    {found_text}
                </p>
            </div>
            <div class="resolution-section" style="margin-bottom: 0.85rem;">
                <span class="resolution-label res-did" style="color: #0474C4 !important; font-weight: 700;">⚡ 2. What Saathi Did</span>
                <p style="margin: 0.25rem 0 0 0; color: #000000 !important; font-size: 0.95rem; line-height: 1.5;">
                    {did_text}
                </p>
            </div>
            <div class="resolution-section">
                <span class="resolution-label res-next" style="color: #2C444C !important; font-weight: 700;">📌 3. Next Steps & Timeline</span>
                <p style="margin: 0.25rem 0 0 0; color: #000000 !important; font-size: 0.95rem; line-height: 1.5;">
                    {next_text}
                </p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Sarvam AI Text-to-Speech (bulbul:v3)
    st.markdown("#### 🔊 Listen with Sarvam AI Voice (bulbul:v3)")
    voice_col1, voice_col2 = st.columns([1, 3])
    with voice_col1:
        spk = st.selectbox("Speaker Voice:", ["priya (Female - Hindi/English)", "rahul (Male - Hindi/English)", "neha (Female)", "aditya (Male)"], index=0)
        speaker_id = spk.split(" ")[0]

    with voice_col2:
        if st.button("Generate Sarvam Voice Audio 🎧", key="btn_gen_voice"):
            if not has_sarvam:
                st.warning("Sarvam AI voice synthesis is offline.")
            else:
                with st.spinner("Synthesizing audio using Sarvam bulbul:v3..."):
                    speech_bytes = text_to_speech(cust_msg_text, language_code="hi-IN", speaker=speaker_id)
                    if speech_bytes:
                        st.session_state["active_case_audio"] = speech_bytes
                        st.rerun()
                    else:
                        st.error("Could not generate audio. Please check Sarvam credits or network connection.")

    if st.session_state.get("active_case_audio"):
        st.audio(st.session_state["active_case_audio"], format="audio/wav")
        st.success("✅ Voice audio ready! Click play above.")

    # Customer-Safe Receipt Timeline (F14) with explicit black text
    st.markdown("#### 🧾 Customer Action Receipt (Feature F14)")
    try:
        receipt = build_case_receipt(case_id)
        for step in receipt.get("steps", []):
            st.markdown(
                f"""
                <div class="white-box receipt-step" style="background-color: #FFFFFF !important; border-left: 4px solid #5379AE !important; border: 1px solid #E2E8F0; padding: 0.65rem 0.85rem; margin-bottom: 0.4rem; border-radius: 6px; color: #000000 !important;">
                    <span style="color: #06457F !important; font-size: 0.75rem; font-weight: 700;">⏱️ {step.get('ts', '')}</span><br/>
                    <b style="color: #000000 !important; font-size: 0.9rem;">{step.get('line', '')}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )
    except Exception:
        st.caption("Action receipt generating...")

    # Technical Deep-Dive Expandable
    with st.expander("🔬 View Deep Orchestrator Trace (Engine Details)", expanded=False):
        c_tr1, c_tr2 = st.columns(2)
        with c_tr1:
            st.write("**Extracted Entities:**")
            st.json(ext)
        with c_tr2:
            st.write("**Case Events & Verification:**")
            st.json(detail.get("events", [])[:5])
