"""
SKU Inventory Risk panel.
Displays SKU stock levels, days of cover, supplier lead times, and predicted risk tiers.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard.api_client import APIClient


def render_sku_heatmap(api_client: APIClient) -> None:
    """Render SKU inventory risk matrix/list."""
    st.subheader("📊 SKU Inventory & Risk Dashboard")

    # Add a filter in Streamlit UI
    selected_tier = st.selectbox(
        "Filter by Risk Level:",
        options=["ALL", "CRITICAL", "WARNING", "WATCH", "NORMAL"],
        index=0,
    )

    filter_tier = None if selected_tier == "ALL" else selected_tier
    sku_data = api_client.fetch_sku_risk(ml_risk_tier=filter_tier)

    if not sku_data:
        st.info("No SKUs match the selected risk filter.")
        return

    # Render as an elegant, styled table
    table_rows = []
    for sku in sku_data:
        sku_id = sku.get("sku_id", "N/A")
        name = sku.get("sku_name", "N/A")
        category = sku.get("category", "N/A").capitalize()
        price = sku.get("unit_price_usd", 0.0)
        stock = sku.get("current_stock", 0)
        lead_time = sku.get("supplier_lead_time_days", 0)
        cover = sku.get("days_of_cover", 0.0)
        tier = sku.get("ml_risk_tier") or "NORMAL"
        below_reorder = sku.get("is_below_reorder", False)

        # Highlight if days of cover is less than supplier lead time (immediate stockout risk)
        is_threatened = cover < lead_time
        warning_indicator = ""
        row_style = ""
        if is_threatened:
            warning_indicator = (
                "⚠️ <span style='color: #e74c3c; font-size: 0.85em; "
                "font-weight: bold;'>Stockout Risk</span>"
            )
            row_style = "background-color: rgba(231, 76, 60, 0.02);"

        # Color-coded tier badges
        if tier == "CRITICAL":
            badge_style = (
                "background-color: rgba(231, 76, 60, 0.2); "
                "color: #e74c3c; border: 1px solid #e74c3c;"
            )
        elif tier == "WARNING":
            badge_style = (
                "background-color: rgba(230, 126, 34, 0.2); "
                "color: #e67e22; border: 1px solid #e67e22;"
            )
        elif tier == "WATCH":
            badge_style = (
                "background-color: rgba(241, 196, 15, 0.2); "
                "color: #f1c40f; border: 1px solid #f1c40f;"
            )
        else:
            badge_style = (
                "background-color: rgba(46, 204, 113, 0.2); "
                "color: #2ecc71; border: 1px solid #2ecc71;"
            )

        below_reorder_badge = (
            "<span style='background-color: rgba(230, 126, 34, 0.15); color: #e67e22; "
            "padding: 2px 6px; border-radius: 4px; font-size: 0.8em;'>Below Reorder</span>"
            if below_reorder
            else "<span style='color: rgba(255, 255, 255, 0.3); font-size: 0.85em;'>OK</span>"
        )

        tr_style = (
            f"{row_style} border-bottom: 1px solid rgba(255, 255, 255, 0.05); "
            "hover: background-color: rgba(255, 255, 255, 0.02);"
        )
        cat_span = (
            f'<span style="background-color: rgba(255, 255, 255, 0.05); '
            f'padding: 3px 8px; border-radius: 12px; font-size: 0.85em;">{category}</span>'
        )
        tier_span = (
            f'<span style="padding: 3px 10px; border-radius: 12px; '
            f'font-weight: bold; font-size: 0.8em; {badge_style}">{tier}</span>'
        )

        row_html = f"""
        <tr style="{tr_style}">
            <td style="padding: 12px; font-weight: bold;">{sku_id}</td>
            <td style="padding: 12px; min-width: 150px;">{name}</td>
            <td style="padding: 12px;">{cat_span}</td>
            <td style="padding: 12px;">${price:.2f}</td>
            <td style="padding: 12px; font-weight: bold;">{stock:,}</td>
            <td style="padding: 12px; color: #3498db; font-weight: bold;">{cover:.1f} days</td>
            <td style="padding: 12px;">{lead_time} days</td>
            <td style="padding: 12px;">{below_reorder_badge}</td>
            <td style="padding: 12px;">{tier_span}</td>
            <td style="padding: 12px;">{warning_indicator}</td>
        </tr>
        """
        table_rows.append(row_html)

    table_body = "\n".join(table_rows)
    div_style = (
        "background-color: #161a23; padding: 15px; border-radius: 10px; "
        "border: 1px solid rgba(255, 255, 255, 0.05); "
        "box-shadow: 0 4px 6px rgba(0,0,0,0.3); overflow-x: auto;"
    )
    html_content = f"""
    <div style="{div_style}">
        <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 0.95em;">
            <thead>
                <tr style="border-bottom: 2px solid rgba(255, 255, 255, 0.1); color: #8892b0;">
                    <th style="padding: 12px;">SKU ID</th>
                    <th style="padding: 12px;">Name</th>
                    <th style="padding: 12px;">Category</th>
                    <th style="padding: 12px;">Price</th>
                    <th style="padding: 12px;">Stock</th>
                    <th style="padding: 12px; color: #3498db;">Days of Cover</th>
                    <th style="padding: 12px;">Lead Time</th>
                    <th style="padding: 12px;">Reorder Check</th>
                    <th style="padding: 12px;">ML Risk Tier</th>
                    <th style="padding: 12px;">Alert</th>
                </tr>
            </thead>
            <tbody>
                {table_body}
            </tbody>
        </table>
    </div>
    """

    # Clean up whitespace/indentation to prevent markdown code block parsing
    html_clean = "\n".join(line.strip() for line in html_content.split("\n"))
    st.markdown(html_clean, unsafe_allow_html=True)
