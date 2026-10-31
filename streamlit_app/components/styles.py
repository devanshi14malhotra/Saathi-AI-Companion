"""
Design tokens & CSS styling for Saathi Autonomous AI Teammate.
Strict adherence to design tokens:
- Page bg: #FFFFFF, surface: #F7F8FA, border: #E5E7EB (1px), text: #111827, muted: #6B7280
- Accent: #0474C4 (Paytm blue, primary actions & active links only)
- Status chips:
  - AUTO: bg #ECFDF3 / text #027A48
  - APPROVE: bg #FFFAEB / text #B54708
  - ESCALATE: bg #FEF3F2 / text #B42318
  - BLOCK: bg #F2F4F7 / text #344054
- Radius: 10px. No shadows. No gradients. No banners.
- Font: Inter with system fallbacks.
- Tabular figures for amounts; small muted monospace for IDs.
"""

from typing import Any
import streamlit as st

# Color Palette & Tokens
PAGE_BG = "#FFFFFF"
SURFACE_BG = "#F7F8FA"
BORDER_COLOR = "#E5E7EB"
TEXT_COLOR = "#111827"
MUTED_COLOR = "#6B7280"
ACCENT_BLUE = "#0474C4"

STATUS_TOKENS = {
    "AUTO": {"bg": "#ECFDF3", "text": "#027A48", "border": "#D1FADF"},
    "APPROVE": {"bg": "#FFFAEB", "text": "#B54708", "border": "#FEDF89"},
    "APPROVED": {"bg": "#ECFDF3", "text": "#027A48", "border": "#D1FADF"},
    "ESCALATE": {"bg": "#FEF3F2", "text": "#B42318", "border": "#FECDCA"},
    "ESCALATED": {"bg": "#FEF3F2", "text": "#B42318", "border": "#FECDCA"},
    "REJECTED": {"bg": "#FEF3F2", "text": "#B42318", "border": "#FECDCA"},
    "BLOCK": {"bg": "#F2F4F7", "text": "#344054", "border": "#EAECF0"},
    "PENDING": {"bg": "#FFFAEB", "text": "#B54708", "border": "#FEDF89"},
    "SUCCESS": {"bg": "#ECFDF3", "text": "#027A48", "border": "#D1FADF"},
    "FAILED": {"bg": "#FEF3F2", "text": "#B42318", "border": "#FECDCA"},
    "DEFAULT": {"bg": "#F2F4F7", "text": "#344054", "border": "#EAECF0"},
}


def inject_custom_css() -> None:
    """Injects clean, professional fintech ops styling."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        /* Base Typography & Max-Width */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
            color: #111827;
        }

        .main .block-container {
            max-width: 1200px;
            padding-top: 1.5rem;
            padding-bottom: 3rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }

        /* Headings */
        h1, h2, h3, h4, h5, h6 {
            color: #111827 !important;
            font-weight: 600 !important;
            letter-spacing: -0.01em;
        }

        h1 {
            font-size: 24px !important;
            margin-bottom: 0.25rem !important;
        }

        h2, h3 {
            font-size: 17px !important;
            margin-top: 1.25rem !important;
            margin-bottom: 0.75rem !important;
        }

        /* Page Header */
        .saathi-page-header {
            margin-bottom: 1.5rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid #E5E7EB;
        }
        .saathi-page-title {
            font-size: 24px;
            font-weight: 600;
            color: #111827;
            margin: 0;
            line-height: 1.25;
        }
        .saathi-page-subtitle {
            font-size: 14px;
            color: #6B7280;
            margin: 0.25rem 0 0 0;
        }

        /* Status Chip */
        .status-chip {
            display: inline-flex;
            align-items: center;
            padding: 2px 8px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            line-height: 1.2;
            letter-spacing: 0.02em;
            text-transform: uppercase;
            border: 1px solid transparent;
            font-variant-numeric: tabular-nums;
        }

        /* ID Chip */
        .id-chip {
            display: inline-block;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 12px;
            color: #4B5563;
            background-color: #F3F4F6;
            border: 1px solid #E5E7EB;
            padding: 1px 6px;
            border-radius: 4px;
        }

        /* Key-Value List */
        .kv-container {
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            background-color: #F7F8FA;
            padding: 0.75rem 1rem;
        }
        .kv-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.45rem 0;
            border-bottom: 1px solid #E5E7EB;
            font-size: 13px;
        }
        .kv-row:last-child {
            border-bottom: none;
        }
        .kv-key {
            color: #6B7280;
            font-weight: 500;
        }
        .kv-val {
            color: #111827;
            font-weight: 600;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }

        /* Confidence Panel */
        .conf-container {
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            background: #FFFFFF;
            padding: 1rem;
        }
        .conf-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 0.75rem;
        }
        .conf-score {
            font-size: 26px;
            font-weight: 700;
            color: #111827;
            font-variant-numeric: tabular-nums;
        }
        .conf-band {
            font-size: 12px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 9999px;
            text-transform: uppercase;
        }
        .conf-bar-group {
            margin-bottom: 0.5rem;
        }
        .conf-bar-label {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #6B7280;
            margin-bottom: 2px;
        }
        .conf-bar-track {
            height: 4px;
            background: #E5E7EB;
            border-radius: 2px;
            overflow: hidden;
        }
        .conf-bar-fill {
            height: 100%;
            background: #0474C4;
            border-radius: 2px;
        }

        /* Timeline */
        .timeline-container {
            border-left: 2px solid #E5E7EB;
            margin-left: 0.5rem;
            padding-left: 1rem;
        }
        .timeline-step {
            position: relative;
            margin-bottom: 0.85rem;
        }
        .timeline-dot {
            position: absolute;
            left: -1.45rem;
            top: 0.2rem;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #0474C4;
            border: 2px solid #FFFFFF;
            box-sizing: content-box;
        }
        .timeline-header {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: #6B7280;
            margin-bottom: 2px;
        }
        .timeline-badge {
            font-size: 11px;
            font-weight: 600;
            color: #111827;
            background: #F3F4F6;
            padding: 1px 5px;
            border-radius: 3px;
        }
        .timeline-summary {
            font-size: 13px;
            color: #111827;
            line-height: 1.4;
        }

        /* KPI Card */
        .kpi-card {
            background-color: #F7F8FA;
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            padding: 0.85rem 1rem;
        }
        .kpi-label {
            font-size: 12px;
            font-weight: 500;
            color: #6B7280;
            margin-bottom: 0.25rem;
        }
        .kpi-value {
            font-size: 22px;
            font-weight: 700;
            color: #111827;
            line-height: 1.1;
            font-variant-numeric: tabular-nums;
        }
        .kpi-sub {
            font-size: 12px;
            color: #6B7280;
            margin-top: 0.25rem;
        }

        /* Buttons & Forms */
        div.stButton > button {
            border-radius: 8px;
            font-weight: 500;
            font-size: 13px;
            border: 1px solid #E5E7EB;
            background: #FFFFFF;
            color: #111827;
            transition: all 0.15s ease;
        }
        div.stButton > button:hover {
            border-color: #D1D5DB;
            background: #F9FAFB;
        }
        div.stButton > button[kind="primary"] {
            background-color: #0474C4 !important;
            color: #FFFFFF !important;
            border: 1px solid #0474C4 !important;
        }
        div.stButton > button[kind="primary"]:hover {
            background-color: #035b9c !important;
            border-color: #035b9c !important;
        }

        /* Streamlit Tabs */
        .stTabs [data-baseweb="tab-list"] {
            gap: 12px;
            border-bottom: 1px solid #E5E7EB;
        }
        .stTabs [data-baseweb="tab"] {
            padding: 8px 12px;
            font-weight: 500;
            font-size: 14px;
            color: #6B7280;
            border-radius: 0;
            border-bottom: 2px solid transparent;
        }
        .stTabs [aria-selected="true"] {
            color: #0474C4 !important;
            border-bottom: 2px solid #0474C4 !important;
            background: transparent !important;
        }

        /* Tables & Dataframes */
        [data-testid="stDataFrame"] {
            border: 1px solid #E5E7EB;
            border-radius: 8px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, badge: str | None = None) -> None:
    """Backward-compatible header renderer (thin wrapper for new page_header)."""
    st.markdown(
        f"""
        <div class="saathi-page-header">
            <h1 class="saathi-page-title">{title}</h1>
            <p class="saathi-page-subtitle">{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, subtitle: str = "") -> None:
    """Backward-compatible metric card renderer (thin wrapper for new KPI)."""
    sub_html = f'<div class="kpi-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{title}</div>
            <div class="kpi-value">{value}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
