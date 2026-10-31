"""
Reusable UI component helpers for Saathi Streamlit pages.
Provides:
- page_header(title, subtitle)
- status_chip(outcome) -> str (HTML string)
- id_chip(text) -> str (HTML string)
- kv_list(dict or list of pairs)
- confidence_panel(conf)
- timeline(events)
- kpi(label, value, sub)
"""

from typing import Any, Mapping
import html
import streamlit as st
from streamlit_app.components.styles import STATUS_TOKENS


def page_header(title: str, subtitle: str | None = None) -> None:
    """Renders a clean page title (24px semibold) with optional muted subtitle."""
    t_safe = html.escape(title)
    sub_html = f'<p class="saathi-page-subtitle">{html.escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<div class="saathi-page-header">'
        f'<h1 class="saathi-page-title">{t_safe}</h1>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def status_chip(outcome: str | None) -> str:
    """Returns an inline HTML status chip formatted as a soft tinted pill."""
    code = (outcome or "DEFAULT").strip().upper()
    tok = STATUS_TOKENS.get(code, STATUS_TOKENS["DEFAULT"])
    return (
        f'<span class="status-chip" style="background-color: {tok["bg"]}; '
        f'color: {tok["text"]}; border-color: {tok["border"]};">{code}</span>'
    )


def id_chip(text: Any) -> str:
    """Returns an inline HTML muted monospace chip for IDs (TXN-..., C-..., RF-...)."""
    return f'<span class="id-chip">{html.escape(str(text))}</span>'


def kv_list(items: Mapping[str, Any] | list[tuple[str, Any]]) -> None:
    """Renders a clean Stripe-style key-value panel."""
    pairs = items.items() if isinstance(items, Mapping) else items
    rows_html = []
    for k, v in pairs:
        val_str = html.escape(str(v)) if v is not None else "—"
        k_str = html.escape(str(k))
        rows_html.append(
            f'<div class="kv-row">'
            f'<span class="kv-key">{k_str}</span>'
            f'<span class="kv-val">{val_str}</span>'
            f'</div>'
        )
    st.markdown(
        f'<div class="kv-container">{"".join(rows_html)}</div>',
        unsafe_allow_html=True,
    )


def confidence_panel(conf: Any) -> None:
    """
    Renders calibrated confidence panel:
    Big score + band label + 4 thin progress bars (understanding, evidence, policy, risk).
    """
    score = 0.0
    band = "MEDIUM"
    und = 0.0
    evi = 0.0
    pol = 0.0
    risk = 0.0

    if isinstance(conf, (int, float)):
        score = float(conf)
        band = "HIGH" if score >= 0.85 else ("MEDIUM" if score >= 0.70 else "LOW")
        und, evi, pol, risk = score, score, score, score
    elif isinstance(conf, dict):
        score = float(conf.get("score") or conf.get("overall") or 0.0)
        band = str(conf.get("band") or ("HIGH" if score >= 0.85 else ("MEDIUM" if score >= 0.70 else "LOW"))).upper()
        und = float(conf["understanding"]) if "understanding" in conf and conf["understanding"] is not None else score
        evi = float(conf["evidence"]) if "evidence" in conf and conf["evidence"] is not None else score
        pol = float(conf["policy"]) if "policy" in conf and conf["policy"] is not None else score
        risk = float(conf["risk"]) if "risk" in conf and conf["risk"] is not None else score

    score_pct = int(score * 100) if score <= 1.0 else int(score)
    band_color = "#027A48" if band == "HIGH" else ("#B54708" if band == "MEDIUM" else "#B42318")
    band_bg = "#ECFDF3" if band == "HIGH" else ("#FFFAEB" if band == "MEDIUM" else "#FEF3F2")

    def make_bar(label: str, val: float) -> str:
        pct = max(0, min(100, int(val * 100) if val <= 1.0 else int(val)))
        return (
            f'<div class="conf-bar-group">'
            f'<div class="conf-bar-label"><span>{html.escape(label)}</span><span>{pct}%</span></div>'
            f'<div class="conf-bar-track"><div class="conf-bar-fill" style="width: {pct}%;"></div></div>'
            f'</div>'
        )

    st.markdown(
        f'<div class="conf-container">'
        f'<div class="conf-header">'
        f'<span class="conf-score">{score_pct}%</span>'
        f'<span class="conf-band" style="background: {band_bg}; color: {band_color};">{band} CONFIDENCE</span>'
        f'</div>'
        f'{make_bar("Understanding", und)}'
        f'{make_bar("Evidence consistency", evi)}'
        f'{make_bar("Policy alignment", pol)}'
        f'{make_bar("Velocity risk", risk)}'
        f'</div>',
        unsafe_allow_html=True,
    )


def timeline(events: list[dict[str, Any]]) -> None:
    """
    Renders GitHub Actions / Stripe style vertical step list:
    Status dot, badge text, summary, and latency_ms. Displays ALL events.
    """
    if not events:
        st.caption("No events recorded.")
        return

    items_html = []
    for ev in events:
        badge = html.escape(str(ev.get("badge") or ev.get("type") or "EVENT").strip())
        summary = html.escape(str(ev.get("summary") or ev.get("event") or "").strip())
        lat = ev.get("latency_ms")
        lat_text = f"• {lat}ms" if lat is not None else ""
        ts = html.escape(str(ev.get("ts") or "")[11:19] if ev.get("ts") else "")

        items_html.append(
            f'<div class="timeline-step">'
            f'<div class="timeline-dot"></div>'
            f'<div class="timeline-header">'
            f'<span class="timeline-badge">{badge}</span>'
            f'<span>{ts}</span>'
            f'<span>{lat_text}</span>'
            f'</div>'
            f'<div class="timeline-summary">{summary}</div>'
            f'</div>'
        )

    st.markdown(
        f'<div class="timeline-container">{"".join(items_html)}</div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: Any, sub: str | None = None) -> None:
    """Renders a single clean KPI metric card."""
    lbl_safe = html.escape(str(label))
    val_safe = html.escape(str(value))
    sub_html = f'<div class="kpi-sub">{html.escape(sub)}</div>' if sub else ""
    st.markdown(
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{lbl_safe}</div>'
        f'<div class="kpi-value">{val_safe}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )
