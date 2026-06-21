"""Training Load page: CTL (fitness), ATL (fatigue), TSB (form) over time.

Reads `mart_training_load`. If `mart_race_events` exists and is non-empty,
overlays vertical markers at each race date. Degrades gracefully when the mart
is empty (e.g. before `make marts`).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from strava_dash.app._shared import get_con, mart

st.title("Training Load — Fitness, Fatigue & Form")
st.caption(
    "CTL (fitness) and ATL (fatigue) are exponentially-weighted averages of "
    "daily training load. TSB = CTL − ATL (form): positive = fresh, negative = "
    "fatigued."
)

con = get_con()
df = mart(con, "mart_training_load")

if df.empty:
    st.info(
        "No training load yet. Run `make fixtures-db` (demo) or `make build` "
        "then `make marts` to populate `mart_training_load`."
    )
    st.stop()

df = df.sort_values("date").reset_index(drop=True)
df["date"] = pd.to_datetime(df["date"])

# --- summary -----------------------------------------------------------------
latest = df.iloc[-1]
c1, c2, c3 = st.columns(3)
c1.metric("Fitness (CTL)", f"{latest['ctl']:.0f}")
c2.metric("Fatigue (ATL)", f"{latest['atl']:.0f}")
c3.metric("Form (TSB)", f"{latest['tsb']:+.0f}")

# --- chart -------------------------------------------------------------------
fig = go.Figure()

# TSB as a filled area around 0 (form).
fig.add_trace(
    go.Scatter(
        x=df["date"], y=df["tsb"], name="Form (TSB)",
        mode="lines", line=dict(color="rgba(120,120,120,0.6)", width=1),
        fill="tozeroy", fillcolor="rgba(120,120,120,0.18)",
        hovertemplate="%{x|%Y-%m-%d}<br>TSB %{y:.0f}<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=df["date"], y=df["ctl"], name="Fitness (CTL)",
        mode="lines", line=dict(color="#1f77b4", width=2.5),
        hovertemplate="%{x|%Y-%m-%d}<br>CTL %{y:.0f}<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=df["date"], y=df["atl"], name="Fatigue (ATL)",
        mode="lines", line=dict(color="#d62728", width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>ATL %{y:.0f}<extra></extra>",
    )
)
fig.add_hline(y=0, line_width=1, line_color="rgba(0,0,0,0.3)")

# --- race markers (defensive: table may be absent or empty) ------------------
races = mart(con, "mart_race_events")
if not races.empty and "date" in races.columns:
    races = races.dropna(subset=["date"]).copy()
    races["date"] = pd.to_datetime(races["date"])
    lo, hi = df["date"].min(), df["date"].max()
    races = races[(races["date"] >= lo) & (races["date"] <= hi)]
    for _, r in races.iterrows():
        fig.add_vline(
            x=r["date"], line_width=1, line_dash="dash",
            line_color="rgba(44,160,44,0.7)",
        )
        fig.add_annotation(
            x=r["date"], yref="paper", y=1.0,
            text=str(r.get("name") or "Race"),
            showarrow=False, textangle=-90, xanchor="left",
            font=dict(size=10, color="rgba(44,160,44,0.9)"),
        )

fig.update_layout(
    height=520, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(t=40, r=20, b=20, l=20),
    yaxis_title="Load",
)
st.plotly_chart(fig, use_container_width=True)

with st.expander("Daily load & values"):
    st.dataframe(
        df[["date", "daily_load", "ctl", "atl", "tsb"]].set_index("date"),
        use_container_width=True,
    )
