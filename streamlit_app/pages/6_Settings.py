"""
System & Provider Settings Workspace
Monitors credentials, dual-account failover, and active model providers.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

# Reload .env
load_dotenv(ROOT_DIR / ".env", override=True)

from streamlit_app.components.styles import inject_custom_css
from streamlit_app.components.ui import page_header, kpi, id_chip, status_chip
from streamlit_app.components.sarvam import check_sarvam_health, get_configured_keys, text_to_speech
from app.core.config import cfg_mgr
from app.llm.provider import get_provider_name

st.set_page_config(page_title="Settings | Saathi", page_icon="⚙️", layout="wide")
inject_custom_css()

page_header(
    title="Settings",
    subtitle="Model configuration, environment credentials, provider switching, and audio health",
)

# Fetch credentials from environment
raw1 = os.environ.get("SARVAM_API_KEY", "").strip()
raw2 = os.environ.get("SARVAM_API_KEY_2", "").strip()
active_provider = get_provider_name()
sarvam_model = cfg_mgr.llm.get("provider_presets", {}).get("sarvam", {}).get("model", "sarvam-105b")


def mask_key(k: str) -> str:
    if not k:
        return "Not configured"
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


st.markdown("### Model and account credentials")

c1, c2, c3 = st.columns(3)
with c1:
    stat_html1 = (
        '<span class="status-chip" style="background:#ECFDF3; color:#027A48; border-color:#D1FADF;">CONFIGURED</span>'
        if raw1 else
        '<span class="status-chip" style="background:#F2F4F7; color:#344054; border-color:#EAECF0;">NOT CONFIGURED</span>'
    )
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Primary account (key 1)</div>
            <div style="margin: 4px 0 6px 0;">{stat_html1}</div>
            <div class="kpi-sub"><code>{mask_key(raw1)}</code></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c2:
    stat_html2 = (
        '<span class="status-chip" style="background:#ECFDF3; color:#027A48; border-color:#D1FADF;">CONFIGURED</span>'
        if raw2 else
        '<span class="status-chip" style="background:#F2F4F7; color:#344054; border-color:#EAECF0;">OPTIONAL</span>'
    )
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">Failover account (key 2)</div>
            <div style="margin: 4px 0 6px 0;">{stat_html2}</div>
            <div class="kpi-sub"><code>{mask_key(raw2)}</code></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c3:
    prov_label = active_provider.upper()
    prov_sub = f"Live Sarvam ({sarvam_model})" if active_provider == "sarvam" else "Deterministic stub (offline)"
    kpi("Active provider", prov_label, prov_sub)

st.write("")
st.markdown("---")

# Health Test
st.markdown("### API connectivity check")
t_col1, t_col2 = st.columns(2)

with t_col1:
    st.markdown("#### Primary account")
    if raw1:
        if st.button("Ping primary account", key="btn_ping_1"):
            with st.spinner("Connecting to Sarvam API with key 1..."):
                res1 = check_sarvam_health(raw1)
                if res1.get("ok"):
                    st.toast("Primary account connected successfully.")
                    st.success(f"Connected: {res1.get('msg')}")
                else:
                    st.error(f"Failed: {res1.get('msg')}")
    else:
        st.caption("Primary key not configured.")

with t_col2:
    st.markdown("#### Failover account")
    if raw2:
        if st.button("Ping failover account", key="btn_ping_2"):
            with st.spinner("Connecting to Sarvam API with key 2..."):
                res2 = check_sarvam_health(raw2)
                if res2.get("ok"):
                    st.toast("Failover account connected successfully.")
                    st.success(f"Connected: {res2.get('msg')}")
                else:
                    st.error(f"Failed: {res2.get('msg')}")
    else:
        st.caption("Failover key not configured.")

st.write("")
st.markdown("---")

# Provider Switcher
st.markdown("### Provider mode selection")
new_provider = st.radio(
    "Choose active LLM provider:",
    [
        "stub — Fast, offline, deterministic local extractor and rewriter",
        f"sarvam — Live Sarvam AI API ({sarvam_model} + bulbul:v3 + saaras:v3)",
    ],
    index=1 if active_provider == "sarvam" else 0,
)

chosen_code = "sarvam" if "sarvam" in new_provider else "stub"

if st.button("Apply provider mode", type="primary"):
    save_key_to_env("LLM_PROVIDER", chosen_code)
    st.toast(f"Switched provider to {chosen_code}.")
    st.rerun()

st.write("")
st.markdown("---")

# Voice Model Test
st.markdown("### Voice synthesis test (bulbul:v3)")
sample_text = st.text_input("Test phrase", value="Paytm Saathi me aapka swagat hai. Main aapka refund check kar rahi hoon.")
if st.button("Synthesize test voice", key="btn_test_voice"):
    keys = get_configured_keys()
    if not keys:
        st.caption("Voice synthesis offline: no API key detected in environment.")
    else:
        with st.spinner("Synthesizing audio using bulbul:v3..."):
            audio = text_to_speech(sample_text, language_code="hi-IN", speaker="priya")
            if audio:
                st.audio(audio, format="audio/wav")
                st.toast("Voice audio generated successfully.")
            else:
                st.error("TTS generation failed. Please verify API key and credit balance.")
