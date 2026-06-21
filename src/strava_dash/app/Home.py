"""Streamlit entry point. Run with: `streamlit run src/strava_dash/app/Home.py`.

This is the foundation shell. The "Overview" work unit expands this landing page;
other pages live under app/pages/ and are picked up automatically by Streamlit.
"""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from strava_dash.app._shared import (
    apply_activity_filters,
    db_ready,
    get_con,
    mart,
    sidebar_filters,
)

st.set_page_config(page_title="Strava Training Dashboard", page_icon="🏃", layout="wide")

st.title("🏃 Strava Training Dashboard")
st.caption("Local, private analysis of your training over time — volume, pace "
           "ranges, pace distribution, and race buildups.")

con = get_con()
flt = sidebar_filters(con)

if not db_ready(con):
    st.warning("No data loaded yet.")
    st.markdown(
        "- **Demo data:** `make fixtures-db` then refresh.\n"
        "- **Your data:** harvest from Strava, then `make build`."
    )
    st.stop()

df = apply_activity_filters(con, flt)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Activities", f"{len(df):,}")
c2.metric("Distance", f"{df['distance_km'].sum():,.0f} km")
c3.metric("Moving time", f"{df['moving_hours'].sum():,.0f} h")
c4.metric("Races", f"{int(df['is_race'].sum()):,}")

# --- Volume over time --------------------------------------------------------
st.subheader("Volume over time")


def _stacked_distance_bar(data, period_label: str, title: str):
    """Stacked distance-by-sport bar chart over `period_start`."""
    fig = px.bar(
        data.sort_values("period_start"),
        x="period_start",
        y="distance_km",
        color="sport",
        labels={"period_start": period_label, "distance_km": "Distance (km)",
                "sport": "Sport"},
        title=title,
    )
    fig.update_layout(barmode="stack", legend_title_text="Sport",
                      xaxis_title=period_label, yaxis_title="Distance (km)")
    return fig


vol = mart(con, "mart_volume")
if vol.empty:
    st.info("No volume data yet. Run `make fixtures-db` (demo) or "
            "`make build` after a real harvest to populate `mart_volume`.")
else:
    # Per-sport rows only (the 'ALL' rollup is excluded so sports never
    # double-count), filtered to the sidebar sport selection.
    sel_sports = flt.get("sports") or []
    per_sport = vol[vol["sport"] != "ALL"]
    if sel_sports:
        per_sport = per_sport[per_sport["sport"].isin(sel_sports)]

    weekly = per_sport[per_sport["period"] == "week"]
    monthly = per_sport[per_sport["period"] == "month"]

    tab_week, tab_month = st.tabs(["Weekly distance", "Monthly volume"])

    with tab_week:
        if weekly.empty:
            st.info("No weekly volume for the current filters.")
        else:
            st.plotly_chart(
                _stacked_distance_bar(weekly, "Week", "Weekly distance by sport"),
                use_container_width=True,
            )

    with tab_month:
        # Monthly distance stacked by sport + total moving hours. Both honor the
        # sport filter: the hours line sums the same filtered per-sport rows
        # (not the 'ALL' rollup) so the two charts stay consistent.
        if monthly.empty:
            st.info("No monthly volume for the current filters.")
        else:
            st.plotly_chart(
                _stacked_distance_bar(monthly, "Month",
                                      "Monthly distance by sport"),
                use_container_width=True,
            )

            hours = (monthly.groupby("period_start", as_index=False)["moving_hours"]
                     .sum().sort_values("period_start"))
            fig_mh = px.area(
                hours,
                x="period_start",
                y="moving_hours",
                labels={"period_start": "Month",
                        "moving_hours": "Moving time (h)"},
                title="Monthly moving hours (selected sports)",
            )
            fig_mh.update_layout(xaxis_title="Month",
                                 yaxis_title="Moving time (h)")
            st.plotly_chart(fig_mh, use_container_width=True)

st.subheader("Recent activities")
cols = ["date", "name", "sport_type", "distance_km", "moving_hours",
        "avg_pace_min_km", "is_race"]
st.dataframe(df.sort_values("date", ascending=False)[cols].head(50),
             use_container_width=True, hide_index=True)

st.info("Use the pages in the sidebar for Overview, Pace Evolution, Race "
        "Buildups, Training Load, and Patterns.")
