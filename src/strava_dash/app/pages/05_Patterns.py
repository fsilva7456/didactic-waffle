"""Patterns & gear: when the athlete trains and what they wear out.

Reads `mart_patterns` (calendar habits) and `mart_gear` (mileage). Renders a
day-of-week x hour-of-day activity heatmap, a seasonality bar, and a gear
mileage table/bar. Degrades gracefully when the marts are empty.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from strava_dash.app._shared import get_con, mart, sidebar_filters

DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]

st.title("Patterns & gear")

con = get_con()
flt = sidebar_filters(con)
sports = flt.get("sports") or []

patterns = mart(con, "mart_patterns")
gear = mart(con, "mart_gear")

if patterns.empty and gear.empty:
    st.info("No pattern or gear data yet. Run `make fixtures-db` (demo) or "
            "`make build && make marts` after a real harvest.")
    st.stop()

# Apply the sidebar sport filter where a selection exists.
if sports and not patterns.empty:
    patterns = patterns[patterns["sport"].isin(sports)]

# --- Day-of-week x hour-of-day heatmap ---------------------------------------
st.subheader("When you train")
dow = patterns[patterns["dimension"] == "dow"] if not patterns.empty else pd.DataFrame()
hour = patterns[patterns["dimension"] == "hour"] if not patterns.empty else pd.DataFrame()

if not dow.empty and not hour.empty:
    # mart_patterns is aggregated per (dimension, bucket, sport) independently, so
    # it cannot give a true dow x hour cross-tab. Derive that directly from
    # activities, respecting the sport filter.
    where = ""
    params: list = []
    if sports:
        placeholders = ", ".join(["?"] * len(sports))
        where = f"WHERE sport_type IN ({placeholders})"
        params = list(sports)
    cross = con.execute(
        f"""
        SELECT dow, hour, count(*) AS n
        FROM activities
        {where}
          {'AND' if where else 'WHERE'} dow IS NOT NULL AND hour IS NOT NULL
        GROUP BY dow, hour
        """,
        params,
    ).df()

    if cross.empty:
        st.caption("No dated activities for the current filter.")
    else:
        grid = (
            cross.pivot(index="dow", columns="hour", values="n")
            .reindex(index=range(7), columns=range(24))
            .fillna(0)
        )
        grid.index = [DOW_LABELS[i] for i in grid.index]
        fig = px.imshow(
            grid,
            labels=dict(x="Hour of day", y="Day of week", color="Activities"),
            aspect="auto",
            color_continuous_scale="Blues",
        )
        fig.update_xaxes(dtick=1)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.caption("No day/hour data available.")

# --- Seasonality -------------------------------------------------------------
st.subheader("Seasonality")
season = patterns[patterns["dimension"] == "season"] if not patterns.empty else pd.DataFrame()
month = patterns[patterns["dimension"] == "month"] if not patterns.empty else pd.DataFrame()

view = st.radio("Group by", ["Season", "Month"], horizontal=True)

if view == "Season" and not season.empty:
    agg = season.groupby("bucket", as_index=False)["distance_km"].sum()
    agg["bucket"] = pd.Categorical(agg["bucket"], categories=SEASON_ORDER, ordered=True)
    agg = agg.sort_values("bucket")
    fig = px.bar(agg, x="bucket", y="distance_km",
                 labels={"bucket": "Season", "distance_km": "Distance (km)"})
    st.plotly_chart(fig, use_container_width=True)
elif view == "Month" and not month.empty:
    agg = month.groupby("bucket", as_index=False)["distance_km"].sum()
    agg["bucket"] = pd.to_datetime(agg["bucket"], errors="coerce")
    agg = agg.dropna(subset=["bucket"]).sort_values("bucket")
    fig = px.bar(agg, x="bucket", y="distance_km",
                 labels={"bucket": "Month", "distance_km": "Distance (km)"})
    st.plotly_chart(fig, use_container_width=True)
else:
    st.caption("No seasonality data available.")

# --- Gear mileage ------------------------------------------------------------
st.subheader("Gear mileage")
if gear.empty:
    st.caption("No gear data available.")
else:
    g = gear.sort_values("distance_km", ascending=False)
    fig = px.bar(
        g, x="distance_km", y="name", orientation="h",
        color="type",
        labels={"distance_km": "Distance (km)", "name": "Gear", "type": "Type"},
    )
    fig.update_layout(yaxis=dict(categoryorder="total ascending"))
    st.plotly_chart(fig, use_container_width=True)

    show = g[["name", "type", "n_activities", "distance_km",
              "first_used", "last_used"]].rename(columns={
        "name": "Gear", "type": "Type", "n_activities": "Activities",
        "distance_km": "Distance (km)", "first_used": "First used",
        "last_used": "Last used"})
    st.dataframe(show, use_container_width=True, hide_index=True)
