"""Streamlit entry point. Run with: `streamlit run src/strava_dash/app/Home.py`.

This is the foundation shell. The "Overview" work unit expands this landing page;
other pages live under app/pages/ and are picked up automatically by Streamlit.
"""
from __future__ import annotations

import streamlit as st

from strava_dash.app._shared import apply_activity_filters, db_ready, get_con, sidebar_filters

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

st.subheader("Recent activities")
cols = ["date", "name", "sport_type", "distance_km", "moving_hours",
        "avg_pace_min_km", "is_race"]
st.dataframe(df.sort_values("date", ascending=False)[cols].head(50),
             use_container_width=True, hide_index=True)

st.info("Use the pages in the sidebar for Overview, Pace Evolution, Race "
        "Buildups, Training Load, and Patterns.")
