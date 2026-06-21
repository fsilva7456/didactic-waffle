"""PRs / best efforts page.

Shows the athlete's running personal records for standard distances and how the
best-effort-to-date for each distance has progressed over time.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from strava_dash.app._shared import get_con, mart
from strava_dash.metrics.prs import STD_DISTANCES, _best_effort_seconds
from strava_dash.util import pace_min_per_km_to_str

# Canonical label order + label->meters map, derived from the metric so the page
# never drifts from the mart (adding a distance there flows through here).
_DIST_ORDER = [label for label, _ in STD_DISTANCES]
_DIST_M = {label: meters for label, meters in STD_DISTANCES}

st.title("PRs / Best Efforts")
st.caption("Fastest running effort covering each standard distance, computed "
           "from per-activity GPS streams.")

con = get_con()
prs = mart(con, "mart_prs")

if prs.empty:
    st.info("No PRs yet. Run `make fixtures-db` (demo) or `make build && "
            "make marts` after a real harvest, then reload.")
    st.stop()

runs = prs[prs["pace_family"] == "run"].copy()
if runs.empty:
    st.info("No running best efforts found.")
    st.stop()


def _fmt_time(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "—"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# --- PR table ----------------------------------------------------------------
order = pd.Categorical(runs["distance_label"], categories=_DIST_ORDER, ordered=True)
runs = runs.assign(_ord=order).sort_values("_ord")

table = pd.DataFrame({
    "Distance": runs["distance_label"],
    "Time": runs["best_seconds"].map(_fmt_time),
    "Pace": runs["pace_min_km"].map(pace_min_per_km_to_str) + " /km",
    "Date": pd.to_datetime(runs["date"]).dt.date.astype(str),
})
st.subheader("Personal records")
st.dataframe(table, hide_index=True, use_container_width=True)

# --- progression: best-effort-to-date per distance over time -----------------
st.subheader("Best-effort progression")
st.caption("Each point is an activity's best effort for that distance; the line "
           "shows the running best-to-date.")

samples = mart(con, "samples")
activities = mart(con, "activities")

prog = pd.DataFrame()
if not samples.empty and not activities.empty:
    run_ids = activities.loc[activities["pace_family"] == "run", "id"].tolist()
    s = samples[samples["activity_id"].isin(run_ids)].copy()
    s = s.dropna(subset=["distance_m", "t"]).sort_values(["activity_id", "t"])
    date_by_act = activities.set_index("id")["date"].to_dict()

    # Only chart distances that actually have a PR (and thus a known target).
    have_labels = [lbl for lbl in runs["distance_label"] if lbl in _DIST_M]
    rows = []
    for aid, g in s.groupby("activity_id", sort=False):
        t = g["t"].astype(float).tolist()
        d = g["distance_m"].astype(float).tolist()
        for label in have_labels:
            target = _DIST_M[label]
            secs = _best_effort_seconds(t, d, target)
            if secs and secs > 0:
                rows.append({
                    "activity_id": aid,
                    "distance_label": label,
                    "date": date_by_act.get(aid),
                    "pace_min_km": (secs / 60.0) / (target / 1000.0),
                    "best_seconds": secs,
                })
    prog = pd.DataFrame(rows)

if prog.empty:
    st.caption("Not enough stream data to chart progression.")
else:
    prog["date"] = pd.to_datetime(prog["date"])
    # Order by date, then fastest-first within a date, so the running best-to-date
    # cummin reflects the best effort achieved on or before each point (ties on the
    # same date resolve to the faster effort instead of a nondeterministic order).
    prog = prog.sort_values(["distance_label", "date", "pace_min_km"])
    prog["best_to_date"] = (
        prog.groupby("distance_label")["pace_min_km"].cummin()
    )
    cat = pd.Categorical(prog["distance_label"], categories=_DIST_ORDER, ordered=True)
    prog = prog.assign(_ord=cat).sort_values(["_ord", "date"])

    fig = px.scatter(
        prog, x="date", y="pace_min_km", color="distance_label",
        category_orders={"distance_label": _DIST_ORDER},
        labels={"pace_min_km": "Pace (min/km)", "date": "Date",
                "distance_label": "Distance"},
        hover_data={"best_seconds": False, "pace_min_km": ":.2f"},
    )
    # overlay the best-to-date line per distance
    for label in _DIST_ORDER:
        sub = prog[prog["distance_label"] == label]
        if sub.empty:
            continue
        fig.add_scatter(x=sub["date"], y=sub["best_to_date"], mode="lines",
                        name=f"{label} best-to-date", line=dict(dash="dot"))
    # faster pace = smaller number; show fastest at top
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)
