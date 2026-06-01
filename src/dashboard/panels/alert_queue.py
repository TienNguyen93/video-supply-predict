"""
Actionable Alert Queue panel.
Displays pending alerts awaiting human approval, showing investigation summaries,
PO drafts, and Approve/Reject buttons.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard.api_client import APIClient


def render_alert_queue(api_client: APIClient) -> None:
    """Render pending replenishment alert queue."""
    st.subheader("🛎️ Actionable Alert Queue")

    pending_alerts = api_client.fetch_alerts(status="PENDING")

    if not pending_alerts:
        st.success("🎉 Clear Queue! No pending alerts requiring approval.")
        return

    st.warning(f"There are {len(pending_alerts)} pending alerts requiring ops verification.")

    for alert in pending_alerts:
        alert_id = alert.get("alert_id")
        if not isinstance(alert_id, str):
            continue
        sku_id = alert.get("sku_id")
        sku_name = alert.get("sku_name", "Unknown SKU")
        tier = alert.get("alert_risk_tier", "WATCH")
        summary = alert.get("investigation_summary", "No investigation details available.")
        action_draft = alert.get("action_draft", "No action draft available.")
        created_at = alert.get("created_at", "N/A")

        # Inventory details
        cover = alert.get("days_of_cover", 0.0)
        stock = alert.get("current_stock", 0)
        lead_time = alert.get("supplier_lead_time_days", 0)

        # Style card based on risk tier
        border_color = "#e74c3c" if tier == "CRITICAL" else "#e67e22"
        bg_color = "#1a2130"

        # Display custom HTML wrapper for the card header
        div_style = (
            f"background-color: {bg_color}; padding: 15px; "
            f"border-left: 6px solid {border_color}; "
            "border-radius: 8px 8px 0px 0px; margin-top: 15px; "
            "border-top: 1px solid rgba(255,255,255,0.05); "
            "border-right: 1px solid rgba(255,255,255,0.05);"
        )
        badge_style = (
            f"background-color: {border_color}22; color: {border_color}; "
            f"border: 1px solid {border_color}; padding: 3px 12px; "
            "border-radius: 12px; font-weight: bold; font-size: 0.85em;"
        )
        card_html = f"""
            <div style="{div_style}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h4 style="margin: 0; color: #fff;">{sku_name} ({sku_id})</h4>
                    <span style="{badge_style}">{tier}</span>
                </div>
                <div style="margin-top: 8px; color: #8892b0; font-size: 0.9em;">
                    <strong>Alert ID:</strong> {alert_id} |
                    <strong>Stock:</strong> {stock:,} units |
                    <strong>Days of Cover:</strong> {cover:.1f} days |
                    <strong>Lead Time:</strong> {lead_time} days
                </div>
            </div>
            """
        card_clean = "\n".join(line.strip() for line in card_html.split("\n"))
        st.markdown(card_clean, unsafe_allow_html=True)

        # Use an st.container for the body and buttons
        with st.container(border=True):
            st.markdown("##### 🔍 Investigation Summary")
            st.markdown(summary)

            st.markdown("##### 📝 Recommended Action Draft")
            st.code(action_draft, language="markdown" if "PO" not in action_draft else "text")

            # Inline action buttons
            col1, col2, col3 = st.columns([1, 1, 2])

            with col1:
                approve_key = f"approve_{alert_id}"
                if st.button("✅ Approve PO / Alert", key=approve_key, use_container_width=True):
                    with st.spinner("Processing approval..."):
                        success = api_client.approve_alert(alert_id, approved_by="ops_manager")
                        if success:
                            st.toast(f"Alert {alert_id} approved!", icon="✅")
                            st.rerun()
                        else:
                            st.error("Failed to approve alert.")

            with col2:
                reject_key = f"reject_{alert_id}"
                if st.button("❌ Dismiss Alert", key=reject_key, use_container_width=True):
                    with st.spinner("Processing dismissal..."):
                        success = api_client.reject_alert(alert_id)
                        if success:
                            st.toast(f"Alert {alert_id} dismissed.", icon="🗑️")
                            st.rerun()
                        else:
                            st.error("Failed to dismiss alert.")

            with col3:
                st.caption(f"Generated at: {created_at}")

        st.write("")  # Spacer
