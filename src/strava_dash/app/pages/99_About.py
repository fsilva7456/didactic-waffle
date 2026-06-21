"""Static about/help page. Also guarantees app/pages/ exists so other page work
units can drop files alongside it without creating the directory."""
import streamlit as st

st.title("About")
st.markdown(
    """
    This dashboard analyzes your Strava training history **locally and privately**.

    **Pipeline**
    1. **Ingest** — harvest activities + per-second streams from Strava into a
       local cache (`data/raw/`).
    2. **Transform** — normalize the cache into a DuckDB database.
    3. **Metrics** — build analytics marts (volume, pace distribution, races,
       training load).
    4. **Dashboard** — these pages.

    **Rebuild:** `make build` (real data) or `make fixtures-db` (demo data),
    then `make marts`.
    """
)
