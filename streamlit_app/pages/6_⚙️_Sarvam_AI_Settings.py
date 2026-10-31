"""
System & Model Health Status
Monitors Sarvam AI connectivity and model availability.
Configure API keys directly in the UI or via environment variables.
"""

import streamlit as st
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

# Reload .env to catch any new user edits
load_dotenv(ROOT_DIR / ".env", override=True)

from streamlit_app.components.styles import inject_custom_css, render_header, render_metric_card
from streamlit_app.components.sarvam import check_sarvam_health, get_configured_keys, text_to_speech

st.set_page_config(page_title="Model Health & Status | Paytm Saathi", page_icon="⚙️", layout="wide")
inject_custom_css()

render_header(
    title="Model Status & Sarvam AI Connectivity",
    subtitle="Environment credentials, dual-account credit failover, and model health monitor",
    badge="System Health",
)

# Fetch keys directly from environment
raw1 = os.environ.get("SARVAM_API_KEY", "").strip()
raw2 = os.environ.get("SARVAM_API_KEY_2", "").strip()

sys.path.insert(0, str(ROOT_DIR / "backend"))
from app.llm.provider import get_provider_name
active_provider = get_provider_name()

def mask_key(k: str) -> str:
    if not k:
        return "Offline / Inactive"
    if len(k) <= 8:
        return "••••••••"
    return f"{k[:4]}••••••••{k[-4:]}"


def save_key_to_env(key_name: str, key_val: str) -> None:
    os.environ[key_name] = key_val
    env_file = ROOT_DIR / ".env"
    try:
        content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        lines = []
        replaced = False
        for line in content.splitlines():
            if line.startswith(f"{key_name}="):
                lines.append(f"{key_name}={key_val}")
                replaced = True
            else:
                lines.append(line)
        if not replaced:
            lines.append(f"{key_name}={key_val}")
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


st.subheader("📋 Account Credentials & Provider Status")
st.write("Credentials and models are loaded from system environment configuration.")

c1, c2, c3 = st.columns(3)
with c1:
    render_metric_card(
        "Account 1 (Primary)",
        "Connected ✅" if raw1 else "Offline ⚪",
        f"Key: {mask_key(raw1)}",
    )
with c2:
    render_metric_card(
        "Account 2 (Failover)",
        "Connected ✅" if raw2 else "Optional ⚪",
        f"Key: {mask_key(raw2)}",
    )
with c3:
    render_metric_card(
        "Active Provider",
        active_provider.upper(),
        "Live Sarvam AI" if active_provider == "sarvam" else "Deterministic Stub (Offline)",
    )

st.markdown("---")

# Health Test
st.subheader("📡 Live API Connectivity & Credit Check")
st.write("Ping Sarvam AI endpoints to verify credit balance and response latency.")

t_col1, t_col2 = st.columns(2)

with t_col1:
    st.markdown("#### Primary Account (Account 1)")
    if raw1:
        if st.button("Check Account 1 Live Ping ⚡", use_container_width=True):
            with st.spinner("Connecting to Sarvam AI with Account 1 key..."):
                res1 = check_sarvam_health(raw1)
                if res1["ok"]:
                    st.success(f"✅ Account 1 Connected: {res1['msg']}")
                else:
                    st.error(f"❌ Account 1 Failed: {res1['msg']}")
    else:
        st.caption("Account status: Offline (Not configured)")

with t_col2:
    st.markdown("#### Failover Pool (Account 2)")
    if raw2:
        if st.button("Check Account 2 Live Ping ⚡", use_container_width=True):
            with st.spinner("Connecting to Sarvam AI with Account 2 key..."):
                res2 = check_sarvam_health(raw2)
                if res2["ok"]:
                    st.success(f"✅ Account 2 Connected: {res2['msg']}")
                else:
                    st.error(f"❌ Account 2 Failed: {res2['msg']}")
    else:
        st.caption("Account status: Offline (Optional failover pool not configured)")

st.markdown("---")

# Provider Switcher
st.subheader("🔀 Active Provider Selection")
new_provider = st.radio(
    "Choose Active LLM Engine:",
    [
        "stub (Fast, offline, 100% deterministic local provider)",
        "sarvam (Live Sarvam AI: sarvam-105b model + bulbul:v3 TTS + saaras:v3 STT)",
    ],
    index=1 if active_provider == "sarvam" else 0,
)

chosen_code = "sarvam" if "sarvam" in new_provider else "stub"

if st.button("Switch Provider Mode"):
    save_key_to_env("LLM_PROVIDER", chosen_code)
    st.success(f"Active provider switched to `{chosen_code}`!")
    st.rerun()

st.markdown("---")

# Voice Synthesizer
st.subheader("🎧 Voice Model Test (bulbul:v3)")
sample_text = st.text_input("Test voice phrase:", value="Paytm Saathi me aapka swagat hai. Main aapka refund check kar rahi hoon.")
if st.button("Synthesize Voice Audio 🔊"):
    keys = get_configured_keys()
    if not keys:
        st.warning("Sarvam AI voice service is offline (no API key detected in environment).")
    else:
        with st.spinner("Generating speech using Sarvam bulbul:v3..."):
            audio = text_to_speech(sample_text, language_code="hi-IN", speaker="priya")
            if audio:
                st.audio(audio, format="audio/wav")
                st.success("Audio playback ready!")
            else:
                st.error("TTS generation failed. Please verify your keys or credit balance.")
