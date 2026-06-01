"""
System Health footer panel.
Displays API connection status, database status, loaded model type, and alert counts.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard.api_client import APIClient


def render_system_health(api_client: APIClient) -> None:
    """Render system health status footer."""
    st.markdown("---")
    st.subheader("⚙️ System Health & Status")

    # Fetch health & alert count stats
    health_data = api_client.check_health()
    alerts = api_client.fetch_alerts()

    # Calculate status counts
    pending_count = sum(1 for a in alerts if a.get("status") == "PENDING")
    approved_count = sum(1 for a in alerts if a.get("status") == "APPROVED")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if health_data:
            style = (
                "background-color: rgba(46, 204, 113, 0.1); "
                "border-left: 5px solid #2ecc71; "
                "padding: 10px; border-radius: 5px;"
            )
            st.markdown(
                f'<div style="{style}">'
                '<span style="color: #2ecc71; font-weight: bold;">● FastAPI API</span><br>'
                f"<small>Endpoint: {api_client.base_url}</small></div>",
                unsafe_allow_html=True,
            )
        else:
            style = (
                "background-color: rgba(231, 76, 60, 0.1); "
                "border-left: 5px solid #e74c3c; "
                "padding: 10px; border-radius: 5px;"
            )
            st.markdown(
                f'<div style="{style}">'
                '<span style="color: #e74c3c; font-weight: bold;">○ FastAPI API Offline</span><br>'
                f"<small>Endpoint: {api_client.base_url}</small></div>",
                unsafe_allow_html=True,
            )

    with col2:
        is_conn = health_data and health_data.get("database") == "connected"
        if is_conn:
            style = (
                "background-color: rgba(46, 204, 113, 0.1); "
                "border-left: 5px solid #2ecc71; "
                "padding: 10px; border-radius: 5px;"
            )
            st.markdown(
                f'<div style="{style}">'
                '<span style="color: #2ecc71; font-weight: bold;">● DuckDB Database</span><br>'
                "<small>Warehouse: Connected</small></div>",
                unsafe_allow_html=True,
            )
        else:
            style = (
                "background-color: rgba(231, 76, 60, 0.1); "
                "border-left: 5px solid #e74c3c; "
                "padding: 10px; border-radius: 5px;"
            )
            st.markdown(
                f'<div style="{style}">'
                '<span style="color: #e74c3c; font-weight: bold;">○ DuckDB Offline</span><br>'
                "<small>Warehouse: Unreachable</small></div>",
                unsafe_allow_html=True,
            )

    with col3:
        model_type = health_data.get("model_load_type", "unknown") if health_data else "offline"
        if model_type in ["mlflow", "local_pickle"]:
            color = "#3498db"  # Blue for registered/local model
            bg_color = "rgba(52, 152, 219, 0.1)"
        elif model_type == "rule_based_fallback":
            color = "#f1c40f"  # Yellow for fallback
            bg_color = "rgba(241, 196, 15, 0.1)"
        else:
            color = "#95a5a6"  # Grey
            bg_color = "rgba(149, 165, 166, 0.1)"

        st.markdown(
            f'<div style="background-color: {bg_color}; border-left: 5px solid {color}; '
            f'padding: 10px; border-radius: 5px;">'
            f'<span style="color: {color}; font-weight: bold;">● Scorer Model</span><br>'
            f"<small>Type: {model_type}</small></div>",
            unsafe_allow_html=True,
        )

    with col4:
        style = (
            "background-color: rgba(255, 255, 255, 0.05); "
            "border-left: 5px solid #9b59b6; "
            "padding: 10px; border-radius: 5px;"
        )
        st.markdown(
            f'<div style="{style}">'
            '<span style="color: #9b59b6; font-weight: bold;">● Alerts Summary</span><br>'
            f"<small>Pending: {pending_count} | Active: {approved_count}</small></div>",
            unsafe_allow_html=True,
        )
