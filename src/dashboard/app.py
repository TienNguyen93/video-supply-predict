"""
Main Streamlit application entrypoint.
Renders the 4-panel dashboard communicating with the FastAPI layer.
"""

from __future__ import annotations

import streamlit as st
import structlog
from streamlit_autorefresh import st_autorefresh

from src.config import settings
from src.dashboard.api_client import APIClient
from src.dashboard.panels.alert_queue import render_alert_queue
from src.dashboard.panels.sku_heatmap import render_sku_heatmap
from src.dashboard.panels.system_health import render_system_health
from src.dashboard.panels.trending_feed import render_trending_feed

log = structlog.get_logger(__name__)

# Set up page configurations
st.set_page_config(
    page_title="Antigravity Demand Lift Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize API client
api_client = APIClient()


def inject_custom_styles() -> None:
    """Inject custom CSS to wows the user with rich design aesthetics."""
    css = """
        <style>
        /* Main background and fonts */
        .stApp {
            background-color: #0d1117;
            font-family: 'Inter', 'Roboto', 'Segoe UI', sans-serif;
            color: #c9d1d9;
        }

        /* Headers and titles */
        h1, h2, h3, h4, h5, h6 {
            color: #f0f6fc !important;
            font-weight: 700 !important;
        }

        /* Customize Streamlit cards / containers */
        div[data-testid="stVerticalBlock"] > div {
            border-radius: 8px;
        }

        /* Sidebar styling */
        section[data-testid="stSidebar"] {
            background-color: #161b22;
            border-right: 1px solid rgba(240, 246, 252, 0.1);
        }

        /* Buttons styling & hover transitions */
        button[kind="secondary"] {
            background-color: #21262d !important;
            color: #c9d1d9 !important;
            border: 1px solid rgba(240, 246, 252, 0.15) !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }
        button[kind="secondary"]:hover {
            border-color: #58a6ff !important;
            color: #58a6ff !important;
            box-shadow: 0 0 8px rgba(88, 166, 255, 0.2) !important;
            transform: translateY(-1px);
        }

        /* Interactive sidebar trigger button */
        button[kind="primary"] {
            background: linear-gradient(135deg, #1f6feb 0%, #0d59b2 100%) !important;
            color: white !important;
            border: none !important;
            border-radius: 6px !important;
            font-weight: bold !important;
            transition: all 0.2s ease !important;
        }
        button[kind="primary"]:hover {
            box-shadow: 0 0 12px rgba(31, 111, 235, 0.4) !important;
            transform: translateY(-1px);
        }

        /* Toast & Toast icon styling */
        div[data-testid="stToast"] {
            background-color: #161b22 !important;
            color: #f0f6fc !important;
            border: 1px solid #30363d !important;
        }
        </style>
    """
    css_clean = "\n".join(line.strip() for line in css.split("\n"))
    st.markdown(css_clean, unsafe_allow_html=True)


def main() -> None:
    log.info("app.py main: starting execution")
    # 1. Inject Styles
    inject_custom_styles()
    log.info("app.py main: styles injected")

    # 2. Configure Auto-Refresh (Every 60s by default)
    refresh_rate_ms = settings.dashboard_refresh_interval_s * 1000
    st_autorefresh(interval=refresh_rate_ms, key="dashboard_autorefresh")
    log.info("app.py main: autorefresh configured")

    # 3. Sidebar Controls
    st.sidebar.markdown("# ⚡ Antigravity Controls")
    st.sidebar.markdown(
        "Viral Short-Video Engagement → SKU Demand Lift Prediction → Agentic Replenishment Alerts"
    )

    st.sidebar.markdown("---")

    # Sidebar Action: Trigger Scoring
    st.sidebar.subheader("🎬 ML Pipeline Actions")
    if st.sidebar.button("🚀 Trigger Model Scoring", use_container_width=True):
        with st.sidebar.spinner("Running model scoring & updating risk..."):
            result = api_client.trigger_scoring()
            if result and result.get("status") == "success":
                scored_count = result.get("scored_videos_count", 0)
                st.sidebar.success(f"Scoring complete! Scored {scored_count} videos.")
                st.toast(f"Scored {scored_count} videos successfully!", icon="📈")
                # Briefly sleep to let user see success, then rerun
                st.rerun()
            else:
                st.sidebar.error("Failed to trigger scoring. Check FastAPI logs.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 Refresh")
    if st.sidebar.button("🔄 Manual Refresh Now", use_container_width=True):
        st.toast("Refreshing data...", icon="🔄")
        st.rerun()

    # Sidebar info footer
    st.sidebar.markdown("")
    st.sidebar.markdown("")
    st.sidebar.markdown(
        """
        <div style="font-size: 0.8em; color: #8b949e; text-align: center;">
            Antigravity replenishment pipeline v1.0.0
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 4. Main Page Title
    st.markdown(
        """
        <div style="margin-bottom: 25px;">
            <h1 style="margin: 0; font-size: 2.3em;">⚡ Antigravity Replenishment Control</h1>
            <p style="margin: 5px 0 0 0; color: #8b949e; font-size: 1.1em;">
                Real-time video demand lift estimation & autonomous ops approval queue.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 5. Render Panel 1: Alert Queue (Full Width)
    log.info("app.py main: rendering alert queue")
    render_alert_queue(api_client)

    st.markdown("<br>", unsafe_allow_html=True)

    # 6. Render Panel 2 & 3: Heatmap and Trending Feed (Side-by-Side Columns)
    col1, col2 = st.columns([6, 5])

    with col1:
        log.info("app.py main: rendering sku heatmap")
        render_sku_heatmap(api_client)

    with col2:
        log.info("app.py main: rendering trending feed")
        render_trending_feed(api_client)

    # 7. Render Panel 4: System Health Footer
    log.info("app.py main: rendering system health")
    render_system_health(api_client)
    log.info("app.py main: execution completed successfully")


if __name__ == "__main__":
    main()
