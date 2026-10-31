"""
Custom UI & Theming for Saathi Autonomous AI Teammate
Strict adherence to the official Paytm Color Palette:
- #0474C4: Primary Electric Blue (Actions, active links, primary buttons)
- #06457F: Deep Paytm Navy (Primary headers, card borders, brand accents)
- #5379AE: Slate Blue (Secondary text, subtitles, subtle borders)
- #A8C4EC: Soft Sky Blue (Background highlights, pills, focus states)
- #262B40: Dark Navy (Dark surfaces, high-contrast text, sidebars)
- #2C444C: Slate Charcoal (Card surfaces, secondary container backgrounds)
"""

import streamlit as st


def inject_custom_css() -> None:
    """Injects high-end, production-grade styling matching the provided color palette."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }

        /* Top Brand Banner */
        .saathi-header {
            background: linear-gradient(135deg, #06457F 0%, #0474C4 100%);
            color: #FFFFFF;
            padding: 1.25rem 1.75rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 14px rgba(4, 116, 196, 0.15);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .saathi-header h1 {
            color: #FFFFFF !important;
            margin: 0;
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }
        .saathi-header p {
            color: #A8C4EC;
            margin: 0.25rem 0 0 0;
            font-size: 0.875rem;
        }

        /* Strict High-Contrast text on white/light surfaces (fixes dark-mode white-on-white) */
        .white-box, .profile-card, .metric-card, .resolution-box, .receipt-step {
            background-color: #FFFFFF !important;
            color: #000000 !important;
        }
        .white-box *, .profile-card *, .metric-card *, .resolution-box *, .receipt-step * {
            color: #000000 !important;
        }
        .white-box b, .profile-card b, .resolution-box b, .receipt-step b {
            color: #000000 !important;
            font-weight: 700 !important;
        }
        .white-box code, .profile-card code {
            background-color: #EEF2F6 !important;
            color: #06457F !important;
            font-weight: 700 !important;
            padding: 2px 6px;
            border-radius: 4px;
        }

        /* Metric Cards */
        .metric-card {
            background-color: #FFFFFF !important;
            border: 1px solid #A8C4EC;
            border-radius: 10px;
            padding: 1.2rem;
            box-shadow: 0 2px 6px rgba(38, 43, 64, 0.04);
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(4, 116, 196, 0.12);
            border-color: #0474C4;
        }
        .metric-title {
            color: #5379AE !important;
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.35rem;
        }
        .metric-value {
            color: #06457F !important;
            font-size: 1.85rem;
            font-weight: 700;
            line-height: 1.1;
        }
        .metric-subtitle {
            color: #2C444C !important;
            font-size: 0.75rem;
            margin-top: 0.35rem;
        }

        /* Custom Resolution Box (Found / Did / Next Steps) */
        .resolution-box {
            background-color: #FFFFFF !important;
            border: 1px solid #A8C4EC;
            border-left: 5px solid #0474C4 !important;
            border-radius: 0 10px 10px 0;
            padding: 1.25rem;
            margin: 1rem 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.03);
        }
        .resolution-section {
            margin-bottom: 0.75rem;
        }
        .resolution-label {
            font-weight: 700;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .res-found { color: #06457F !important; }
        .res-did { color: #0474C4 !important; }
        .res-next { color: #2C444C !important; }

        /* Status Pills */
        .status-pill {
            display: inline-block;
            padding: 0.25rem 0.65rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }
        .pill-success {
            background-color: #E8F5E9;
            color: #1B5E20;
            border: 1px solid #A5D6A7;
        }
        .pill-pending {
            background-color: #FFF8E1;
            color: #E65100;
            border: 1px solid #FFE082;
        }
        .pill-failed {
            background-color: #FFEBEE;
            color: #B71C1C;
            border: 1px solid #FFCDD2;
        }
        .pill-info {
            background-color: #E3F2FD;
            color: #06457F;
            border: 1px solid #A8C4EC;
        }

        /* Customer Receipt Step */
        .receipt-step {
            padding: 0.65rem 0.85rem;
            margin-bottom: 0.4rem;
            border-radius: 6px;
            background: #FFFFFF;
            border-left: 3px solid #5379AE;
            font-size: 0.85rem;
            color: #262B40;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
        }

        /* Buttons */
        div.stButton > button {
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.2s ease;
        }
        div.stButton > button[kind="primary"] {
            background-color: #0474C4;
            color: #FFFFFF;
            border: none;
        }
        div.stButton > button[kind="primary"]:hover {
            background-color: #06457F;
            box-shadow: 0 4px 12px rgba(4, 116, 196, 0.25);
        }

        /* Streamlit Tabs */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 6px 6px 0 0;
            padding: 8px 16px;
            font-weight: 600;
            color: #5379AE;
        }
        .stTabs [aria-selected="true"] {
            background-color: #FFFFFF !important;
            color: #0474C4 !important;
            border-bottom: 2px solid #0474C4 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str, badge: str = "Paytm Saathi AI") -> None:
    st.markdown(
        f"""
        <div class="saathi-header">
            <div>
                <h1>{title}</h1>
                <p>{subtitle}</p>
            </div>
            <div style="background: rgba(255,255,255,0.15); padding: 0.35rem 0.85rem; border-radius: 20px; font-size: 0.8rem; font-weight: 600; border: 1px solid rgba(255,255,255,0.3);">
                {badge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(title: str, value: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">{title}</div>
            <div class="metric-value">{value}</div>
            {f'<div class="metric-subtitle">{subtitle}</div>' if subtitle else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

