"""Strava training dashboard — local, private analytics over your Strava history.

Pipeline layers:
    ingest    -> harvest raw activity + stream JSON into data/raw/ (via Strava MCP)
    transform -> normalize the raw cache into DuckDB tables (activities, samples,
                 pace_histograms)
    metrics   -> build analytics "marts" (volume, pace distribution, races, load)
    app       -> Streamlit dashboard reading the marts

The transform + metrics layers are pure functions over the local cache/DB, so the
whole thing can be rebuilt offline and tested against synthetic fixtures.
"""

__version__ = "0.1.0"
