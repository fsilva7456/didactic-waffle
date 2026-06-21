"""Shared helpers for Streamlit pages. COMPLETE — page work units import from
here but must not modify it, so pages stay independently mergeable.

Provides a cached read-only DuckDB connection, the global sidebar filters, and
small dataframe helpers. Every page should:

    from strava_dash.app._shared import get_con, sidebar_filters, mart

    con = get_con()
    flt = sidebar_filters(con)
    df = mart(con, "mart_volume")
"""
from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from ..paths import db_path
from ..util import load_config


@st.cache_resource
def get_con() -> duckdb.DuckDBPyConnection:
    """Read-only connection (cached across reruns). Falls back to an empty
    in-memory DB with the schema if the file is missing, so the app still loads
    and shows an onboarding hint instead of crashing."""
    p = db_path()
    if not p.exists():
        from .. import schema
        con = duckdb.connect(":memory:")
        schema.ensure_core(con)
        schema.ensure_marts(con)
        return con
    return duckdb.connect(str(p), read_only=True)


def db_ready(con) -> bool:
    try:
        return con.execute("SELECT count(*) FROM activities").fetchone()[0] > 0
    except Exception:
        return False


def mart(con, table: str) -> pd.DataFrame:
    """Read a mart/core table as a DataFrame; empty frame if missing."""
    try:
        return con.execute(f"SELECT * FROM {table}").df()
    except Exception:
        return pd.DataFrame()


def config() -> dict:
    return load_config()


def sidebar_filters(con) -> dict:
    """Render the shared sidebar filters and return the selections."""
    st.sidebar.header("Filters")
    if not db_ready(con):
        st.sidebar.info("No data yet. Run `make fixtures-db` (demo) or "
                        "`make build` after a real harvest.")
        return {"sports": [], "date_range": None, "pace_family": "run"}

    sports = [r[0] for r in con.execute(
        "SELECT DISTINCT sport_type FROM activities ORDER BY 1").fetchall()]
    sel_sports = st.sidebar.multiselect("Sport", sports, default=sports)

    dmin, dmax = con.execute("SELECT min(date), max(date) FROM activities").fetchone()
    date_range = st.sidebar.date_input("Date range", value=(dmin, dmax),
                                       min_value=dmin, max_value=dmax)

    fam = st.sidebar.selectbox("Pace family", ["run", "swim", "ride"], index=0)
    return {"sports": sel_sports, "date_range": date_range, "pace_family": fam}


def apply_activity_filters(con, flt: dict) -> pd.DataFrame:
    """Convenience: filtered activities DataFrame for the current selections."""
    df = mart(con, "activities")
    if df.empty:
        return df
    if flt.get("sports"):
        df = df[df["sport_type"].isin(flt["sports"])]
    dr = flt.get("date_range")
    if dr and isinstance(dr, (list, tuple)) and len(dr) == 2:
        lo, hi = pd.Timestamp(dr[0]), pd.Timestamp(dr[1])
        d = pd.to_datetime(df["date"])
        df = df[(d >= lo) & (d <= hi)]
    return df
