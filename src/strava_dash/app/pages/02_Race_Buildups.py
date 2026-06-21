"""Race Buildups — overlay how training ramped into each race.

The key question: "how my training led up to various races — specifically
volume and pace ranges." Pick one or more races and compare their N-week
buildups aligned on ``weeks_to_race`` (race week at the right):

* weekly volume ramp (distance per week, per sport),
* long-run progression (max single run per week),
* run pace trend (mean weekly run pace; lower = faster).

Reads the ``mart_race_events`` / ``mart_race_buildup`` marts. Degrades
gracefully when those are empty (no races detected / DB not built yet).
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from strava_dash.app._shared import config, get_con, mart
from strava_dash.util import pace_min_per_km_to_str

st.title("Race Buildups")
st.caption(
    "Compare how training volume, long runs and pace ramped into each race. "
    "Buildups are aligned on weeks-to-race (race week at the right)."
)

con = get_con()
events = mart(con, "mart_race_events")
buildup = mart(con, "mart_race_buildup")

if events.empty or buildup.empty:
    st.info(
        "No race buildups yet. Detect races and build marts first "
        "(`make fixtures-db` for demo data, or `make build` after a harvest), "
        "then rebuild marts with `python -m strava_dash.cli marts`."
    )
    st.stop()

events = events.sort_values("date")


def _event_label(row: pd.Series) -> str:
    name = row.get("name") or row["event_id"]
    date = row.get("date")
    prio = row.get("priority")
    label = f"{name} ({date})" if pd.notna(date) else str(name)
    if isinstance(prio, str) and prio:
        label = f"[{prio}] {label}"
    return label


raw_labels = {r["event_id"]: _event_label(r) for _, r in events.iterrows()}
# Disambiguate any colliding labels so each race stays independently selectable
# (event_id is the only guaranteed-unique key).
counts: dict[str, int] = {}
for lbl in raw_labels.values():
    counts[lbl] = counts.get(lbl, 0) + 1
labels = {
    event_id: (f"{lbl} · {event_id}" if counts[lbl] > 1 else lbl)
    for event_id, lbl in raw_labels.items()
}
label_to_id = {v: k for k, v in labels.items()}

# Default: select all races so the comparison is visible immediately.
default_labels = list(labels.values())
picked_labels = st.multiselect(
    "Races to compare",
    options=list(labels.values()),
    default=default_labels,
)
picked_ids = [label_to_id[lbl] for lbl in picked_labels]

if not picked_ids:
    st.info("Pick at least one race above to see its buildup.")
    st.stop()

sports = sorted(buildup["sport"].dropna().unique().tolist())
sel_sports = st.multiselect("Sports (volume ramp)", sports, default=sports)

bu = buildup[buildup["event_id"].isin(picked_ids)].copy()
bu["race"] = bu["event_id"].map(labels)

# x-axis reversed so the race week (weeks_to_race = 0) sits on the right.
x_max = int(bu["weeks_to_race"].max()) if not bu.empty else 0
x_axis = dict(title="Weeks to race", autorange="reversed", dtick=1, range=[x_max + 0.5, -0.5])


# --- 1) Weekly volume ramp ---------------------------------------------------
st.subheader("Weekly volume ramp")
vol_src = bu[bu["sport"].isin(sel_sports)] if sel_sports else bu
vol = (
    vol_src.groupby(["race", "weeks_to_race"], as_index=False)["distance_km"].sum()
)
if vol.empty:
    st.caption("No volume in the selected window for these races/sports.")
else:
    fig_vol = px.line(
        vol.sort_values("weeks_to_race"),
        x="weeks_to_race",
        y="distance_km",
        color="race",
        markers=True,
        labels={"distance_km": "Distance (km)", "weeks_to_race": "Weeks to race"},
    )
    fig_vol.update_layout(xaxis=x_axis, legend_title_text="Race", hovermode="x unified")
    st.plotly_chart(fig_vol, use_container_width=True)


# --- 2) Long-run progression -------------------------------------------------
st.subheader("Long-run progression")
cfg = config()
long_min = (cfg.get("buildup", {}) or {}).get("long_run_min_km")
runs = bu[bu["sport"] == "Run"]
lr = (
    runs.dropna(subset=["long_run_km"])
    .groupby(["race", "weeks_to_race"], as_index=False)["long_run_km"].max()
)
if lr.empty:
    st.caption("No runs in the selected window for these races.")
else:
    fig_lr = px.line(
        lr.sort_values("weeks_to_race"),
        x="weeks_to_race",
        y="long_run_km",
        color="race",
        markers=True,
        labels={"long_run_km": "Longest run (km)", "weeks_to_race": "Weeks to race"},
    )
    fig_lr.update_layout(xaxis=x_axis, legend_title_text="Race", hovermode="x unified")
    if long_min:
        fig_lr.add_hline(
            y=float(long_min),
            line_dash="dot",
            line_color="gray",
            annotation_text=f"long-run threshold ({long_min:g} km)",
            annotation_position="top left",
        )
    st.plotly_chart(fig_lr, use_container_width=True)


# --- 3) Run pace trend -------------------------------------------------------
st.subheader("Run pace trend")
st.caption("Mean weekly run pace (min/km). Lower is faster.")
pace = (
    bu[bu["sport"] == "Run"]
    .dropna(subset=["avg_pace_min_km"])
    .groupby(["race", "weeks_to_race"], as_index=False)["avg_pace_min_km"].mean()
)
if pace.empty:
    st.caption("No run pace in the selected window for these races.")
else:
    fig_pace = go.Figure()
    for race, grp in pace.groupby("race"):
        grp = grp.sort_values("weeks_to_race")
        fig_pace.add_trace(
            go.Scatter(
                x=grp["weeks_to_race"],
                y=grp["avg_pace_min_km"],
                mode="lines+markers",
                name=race,
                customdata=[pace_min_per_km_to_str(p) for p in grp["avg_pace_min_km"]],
                hovertemplate="%{customdata} min/km<extra>%{fullData.name}</extra>",
            )
        )
    # Faster paces (smaller numbers) at the top reads as "improving upward".
    fig_pace.update_layout(
        xaxis=x_axis,
        yaxis=dict(title="Pace (min/km)", autorange="reversed"),
        legend_title_text="Race",
        hovermode="x unified",
    )
    st.plotly_chart(fig_pace, use_container_width=True)


# --- Detail table ------------------------------------------------------------
with st.expander("Buildup data"):
    show = bu.sort_values(["race", "weeks_to_race", "sport"])[
        [
            "race", "weeks_to_race", "week_start", "sport",
            "distance_km", "moving_hours", "long_run_km",
            "avg_pace_min_km", "n_activities",
        ]
    ]
    st.dataframe(show, use_container_width=True, hide_index=True)
