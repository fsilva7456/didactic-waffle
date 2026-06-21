"""Pace Evolution — the headline view: how pace *ranges* and the pace
*distribution* have changed over time.

Reads two marts built by ``metrics/pace_evolution.py``:
* ``mart_pace_distribution`` — stacked-area of time-share per pace bucket
  across periods (how the distribution shifts).
* ``mart_pace_range`` — median-pace line with a p10–p90 band over time.

Degrades gracefully when the marts are empty (e.g. before `make marts`).
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from strava_dash.app._shared import config, get_con, mart, sidebar_filters

# Lower pace number = faster for run (min/km) and swim (min/100m); for ride the
# metric is km/h so higher = faster. Used to orient the y-axis.
_LOWER_IS_FASTER = {"run": True, "swim": True, "ride": False}
_METRIC_UNIT = {"run": "min/km", "swim": "min/100m", "ride": "km/h"}

st.set_page_config(page_title="Pace Evolution", page_icon="📈", layout="wide")
st.title("📈 Pace Evolution")
st.caption("How your pace ranges and pace distribution have changed over time.")

con = get_con()
flt = sidebar_filters(con)

period = (config().get("trends", {}) or {}).get("period", "quarter")

rng = mart(con, "mart_pace_range")
dist = mart(con, "mart_pace_distribution")

if rng.empty and dist.empty:
    st.info(
        "No pace-evolution data yet. Build it with `make fixtures-db` (demo) or "
        "`make build` (your data), then `make marts`."
    )
    st.stop()

# Available families across both marts (run/swim/ride), defaulting to run.
fams = sorted(
    set(rng["pace_family"].unique() if not rng.empty else [])
    | set(dist["pace_family"].unique() if not dist.empty else [])
)
if not fams:
    st.info("No run/swim/ride activities to analyze.")
    st.stop()

default_fam = flt.get("pace_family", "run")
default_idx = fams.index(default_fam) if default_fam in fams else 0
fam = st.selectbox(
    "Pace family", fams, index=default_idx,
    help="Run = min/km, Swim = min/100m, Ride = km/h.",
)
unit = _METRIC_UNIT.get(fam, "")
faster_note = "lower = faster" if _LOWER_IS_FASTER.get(fam, True) else "higher = faster"
st.caption(f"Metric for **{fam}**: {unit} ({faster_note}). Period bucket: **{period}**.")

# --- (a) Distribution evolution ---------------------------------------------
st.subheader("Pace distribution over time")
st.caption("Share of moving time spent in each pace bucket, per period — watch "
           "the mass shift toward faster buckets as fitness improves.")

dfam = dist[dist["pace_family"] == fam].copy() if not dist.empty else pd.DataFrame()
if dfam.empty:
    st.info("No distribution data for this pace family.")
else:
    dfam = dfam.sort_values(["period_start", "bucket_idx"])
    # Stable bucket ordering (by bucket_idx) for a coherent stacked-area legend.
    bucket_order = (
        dfam[["bucket_idx", "bucket_label"]]
        .drop_duplicates()
        .sort_values("bucket_idx")["bucket_label"]
        .tolist()
    )
    fig = px.area(
        dfam,
        x="period_start",
        y="share",
        color="bucket_label",
        category_orders={"bucket_label": bucket_order},
        labels={"period_start": "Period", "share": "Share of time",
                "bucket_label": f"Pace bucket ({unit})"},
        color_discrete_sequence=px.colors.sequential.Viridis,
    )
    fig.update_layout(yaxis_tickformat=".0%", hovermode="x unified",
                      legend_title_text=f"Pace bucket ({unit})")
    st.plotly_chart(fig, use_container_width=True)

# --- (b) Median pace with p10–p90 band --------------------------------------
st.subheader("Median pace with p10–p90 band")
st.caption("Median per-activity pace over time, with the shaded p10–p90 range "
           "showing spread.")

rfam = rng[rng["pace_family"] == fam].copy() if not rng.empty else pd.DataFrame()
if rfam.empty:
    st.info("No pace-range data for this pace family.")
else:
    rfam = rfam.sort_values("period_start")
    x = rfam["period_start"]
    fig2 = go.Figure()
    # p10–p90 band (upper then lower with fill).
    fig2.add_trace(go.Scatter(
        x=x, y=rfam["p90"], mode="lines", line=dict(width=0),
        name="p90", hoverinfo="skip", showlegend=False,
    ))
    fig2.add_trace(go.Scatter(
        x=x, y=rfam["p10"], mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(99,110,250,0.2)",
        name="p10–p90", hoverinfo="skip",
    ))
    # Median line.
    fig2.add_trace(go.Scatter(
        x=x, y=rfam["p50"], mode="lines+markers",
        line=dict(color="rgb(99,110,250)", width=2), name="median (p50)",
    ))
    fig2.update_layout(
        xaxis_title="Period",
        yaxis_title=f"Pace ({unit})",
        hovermode="x unified",
    )
    # Orient axis so "faster" reads intuitively (faster toward top).
    if _LOWER_IS_FASTER.get(fam, True):
        fig2.update_yaxes(autorange="reversed")
    st.plotly_chart(fig2, use_container_width=True)

    st.dataframe(
        rfam[["period", "period_start", "p10", "p25", "p50", "p75", "p90",
              "n_activities"]].reset_index(drop=True),
        use_container_width=True, hide_index=True,
    )
