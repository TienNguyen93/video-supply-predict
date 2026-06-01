"""
Trending Videos Feed panel.
Displays latest viral videos sorted by predicted P90 demand lift and engagement metrics.
"""

from __future__ import annotations

import streamlit as st

from src.dashboard.api_client import APIClient


def render_trending_feed(api_client: APIClient) -> None:
    """Render trending videos feed panel."""
    st.subheader("🔥 Trending Scored Videos")

    videos = api_client.fetch_trending_videos()

    if not videos:
        st.info("No trending videos scored yet. Trigger model inference to compute predictions.")
        return

    # Modern card grid or customized HTML table for visual excellence
    table_rows = []
    for vid in videos:
        video_id = vid.get("video_id", "N/A")
        platform = vid.get("platform", "N/A").upper()
        creator = vid.get("creator_tier", "N/A").capitalize()
        views = vid.get("total_views", 0)
        p50_lift = vid.get("p50_demand_lift")
        p90_lift = vid.get("p90_demand_lift")
        tier = vid.get("risk_tier_predicted") or "NORMAL"
        sku_json = vid.get("sku_ids_json") or "[]"

        # Platform emoji mapping
        pf_emoji = "🎵" if "TIKTOK" in platform else "📸" if "INSTAGRAM" in platform else "🎥"

        # Tier styling badge
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

        # Format lifts
        p50_str = f"{p50_lift:.2f}x" if p50_lift is not None else "N/A"
        p90_str = f"{p90_lift:.2f}x" if p90_lift is not None else "N/A"

        creator_span = (
            f'<span style="background-color: rgba(255, 255, 255, 0.05); '
            f'padding: 3px 8px; border-radius: 12px; font-size: 0.85em;">{creator}</span>'
        )
        sku_td_style = (
            "font-family: monospace; font-size: 0.9em; max-width: 150px; "
            "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
        )
        tier_span = (
            f'<span style="padding: 3px 10px; border-radius: 12px; '
            f'font-weight: bold; font-size: 0.8em; {badge_style}">{tier}</span>'
        )

        row_html = f"""
        <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                   hover: background-color: rgba(255, 255, 255, 0.02);">
            <td style="padding: 12px; font-weight: bold;">{video_id}</td>
            <td style="padding: 12px;">{pf_emoji} {platform}</td>
            <td style="padding: 12px;">{creator_span}</td>
            <td style="padding: 12px; font-weight: bold;">{views:,}</td>
            <td style="padding: 12px; color: #3498db; font-weight: bold;">{p50_str}</td>
            <td style="padding: 12px; color: #e74c3c; font-weight: bold;">{p90_str}</td>
            <td style="padding: 12px; {sku_td_style}" title='{sku_json}'>{sku_json}</td>
            <td style="padding: 12px;">{tier_span}</td>
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
                    <th style="padding: 12px;">Video ID</th>
                    <th style="padding: 12px;">Platform</th>
                    <th style="padding: 12px;">Creator</th>
                    <th style="padding: 12px;">Views</th>
                    <th style="padding: 12px;">P50 Lift</th>
                    <th style="padding: 12px; color: #e74c3c;">P90 Lift</th>
                    <th style="padding: 12px;">SKUs</th>
                    <th style="padding: 12px;">Risk Predicted</th>
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
