"""DuckDB schema: the contract shared by every layer.

* CORE tables are produced by the transform layer from the raw/fixtures cache.
* MART tables are produced by the metrics layer. They are declared here (and
  created empty by `ensure_marts`) so the dashboard can query them even before a
  given metric module has been merged — an absent metric just yields an empty
  table rather than an import error. Metric modules MUST keep these column
  contracts stable; add columns rather than rename.
"""
from __future__ import annotations

import duckdb

# --- CORE tables (built by transform.py) -------------------------------------

CORE_DDL: dict[str, str] = {
    "activities": """
        CREATE TABLE IF NOT EXISTS activities (
            id              BIGINT PRIMARY KEY,
            name            VARCHAR,
            sport_type      VARCHAR,
            pace_family     VARCHAR,        -- run | swim | ride | other
            start_local     TIMESTAMP,
            date            DATE,
            year            INTEGER,
            month           DATE,           -- first day of month
            quarter         VARCHAR,        -- e.g. 2025-Q2
            iso_week        DATE,           -- Monday of the ISO week
            season          VARCHAR,        -- Winter/Spring/Summer/Fall
            dow             INTEGER,        -- 0=Mon .. 6=Sun
            hour            INTEGER,
            distance_m      DOUBLE,
            distance_km     DOUBLE,
            moving_time_s   INTEGER,
            elapsed_time_s  INTEGER,
            moving_hours    DOUBLE,
            avg_speed_mps   DOUBLE,
            max_speed_mps   DOUBLE,
            avg_pace_min_km DOUBLE,         -- for run-family; null otherwise
            elevation_gain  DOUBLE,
            avg_hr          DOUBLE,
            max_hr          DOUBLE,
            avg_cadence     DOUBLE,
            relative_effort DOUBLE,
            calories        DOUBLE,
            gear_id         VARCHAR,
            workout_type    INTEGER,
            is_race         BOOLEAN DEFAULT FALSE,
            race_event_id   VARCHAR,        -- groups tri swim/bike/run on a day
            race_name       VARCHAR,
            has_streams     BOOLEAN DEFAULT FALSE
        )
    """,
    # Downsampled per-activity time series (kept compact). One row per sample.
    "samples": """
        CREATE TABLE IF NOT EXISTS samples (
            activity_id   BIGINT,
            t             INTEGER,          -- seconds from start
            distance_m    DOUBLE,
            speed_mps     DOUBLE,
            pace_min_km   DOUBLE,
            heartrate     DOUBLE,
            altitude      DOUBLE,
            cadence       DOUBLE,
            moving        BOOLEAN
        )
    """,
    # Time-in-pace-bucket per activity — the compact basis for distribution
    # analysis. metric (pace_bucket) edges come from config; seconds are weighted
    # by sample dt and restricted to moving samples.
    "pace_histograms": """
        CREATE TABLE IF NOT EXISTS pace_histograms (
            activity_id   BIGINT,
            pace_family   VARCHAR,
            bucket_idx    INTEGER,
            bucket_label  VARCHAR,
            seconds       DOUBLE
        )
    """,
    "athlete": """
        CREATE TABLE IF NOT EXISTS athlete (
            id            BIGINT,
            first_name    VARCHAR,
            last_name     VARCHAR,
            measurement   VARCHAR,
            weight        DOUBLE,
            raw           JSON
        )
    """,
    "gear": """
        CREATE TABLE IF NOT EXISTS gear (
            id            VARCHAR PRIMARY KEY,
            name          VARCHAR,
            type          VARCHAR,          -- shoe | bike
            raw           JSON
        )
    """,
}

# --- MART tables (built by metrics/*.py) -------------------------------------
# Each entry: table name -> column definition. Created empty by ensure_marts so
# the dashboard degrades gracefully when a metric hasn't been built yet.

MART_DDL: dict[str, str] = {
    "mart_volume": """
        CREATE TABLE IF NOT EXISTS mart_volume (
            period        VARCHAR,          -- week | month
            period_start  DATE,
            sport         VARCHAR,          -- sport_type or 'ALL'
            pace_family   VARCHAR,
            distance_km   DOUBLE,
            moving_hours  DOUBLE,
            n_activities  INTEGER,
            elevation_gain DOUBLE
        )
    """,
    "mart_pace_range": """
        CREATE TABLE IF NOT EXISTS mart_pace_range (
            period        VARCHAR,
            period_start  DATE,
            pace_family   VARCHAR,
            p10           DOUBLE,
            p25           DOUBLE,
            p50           DOUBLE,
            p75           DOUBLE,
            p90           DOUBLE,
            n_activities  INTEGER
        )
    """,
    "mart_pace_distribution": """
        CREATE TABLE IF NOT EXISTS mart_pace_distribution (
            period        VARCHAR,
            period_start  DATE,
            pace_family   VARCHAR,
            bucket_idx    INTEGER,
            bucket_label  VARCHAR,
            seconds       DOUBLE,
            share         DOUBLE            -- fraction of period time in bucket
        )
    """,
    "mart_race_events": """
        CREATE TABLE IF NOT EXISTS mart_race_events (
            event_id      VARCHAR PRIMARY KEY,
            date          DATE,
            name          VARCHAR,
            priority      VARCHAR,
            sports        VARCHAR,          -- comma-joined sport set
            n_activities  INTEGER
        )
    """,
    "mart_race_buildup": """
        CREATE TABLE IF NOT EXISTS mart_race_buildup (
            event_id        VARCHAR,
            race_name       VARCHAR,
            weeks_to_race   INTEGER,        -- 0 = race week, 1 = week before, ...
            week_start      DATE,
            sport           VARCHAR,
            distance_km     DOUBLE,
            moving_hours    DOUBLE,
            long_run_km     DOUBLE,
            avg_pace_min_km DOUBLE,
            n_activities    INTEGER
        )
    """,
    "mart_training_load": """
        CREATE TABLE IF NOT EXISTS mart_training_load (
            date          DATE,
            daily_load    DOUBLE,
            ctl           DOUBLE,           -- fitness
            atl           DOUBLE,           -- fatigue
            tsb           DOUBLE            -- form (ctl - atl)
        )
    """,
    "mart_prs": """
        CREATE TABLE IF NOT EXISTS mart_prs (
            pace_family     VARCHAR,
            distance_label  VARCHAR,        -- 1k, 5k, 10k, HM, ...
            distance_m      DOUBLE,
            best_seconds    DOUBLE,
            pace_min_km     DOUBLE,
            activity_id     BIGINT,
            date            DATE
        )
    """,
    "mart_patterns": """
        CREATE TABLE IF NOT EXISTS mart_patterns (
            dimension     VARCHAR,          -- dow | hour | season | month
            bucket        VARCHAR,
            sport         VARCHAR,
            n_activities  INTEGER,
            distance_km   DOUBLE,
            moving_hours  DOUBLE
        )
    """,
    "mart_gear": """
        CREATE TABLE IF NOT EXISTS mart_gear (
            gear_id       VARCHAR,
            name          VARCHAR,
            type          VARCHAR,
            n_activities  INTEGER,
            distance_km   DOUBLE,
            first_used    DATE,
            last_used     DATE
        )
    """,
}


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    from .paths import db_path
    return duckdb.connect(str(db_path()), read_only=read_only)


def ensure_core(con: duckdb.DuckDBPyConnection) -> None:
    for ddl in CORE_DDL.values():
        con.execute(ddl)


def ensure_marts(con: duckdb.DuckDBPyConnection) -> None:
    """Create empty mart tables if absent so the dashboard never 500s on a
    not-yet-built metric."""
    for ddl in MART_DDL.values():
        con.execute(ddl)


def reset_core(con: duckdb.DuckDBPyConnection) -> None:
    for name in CORE_DDL:
        con.execute(f"DROP TABLE IF EXISTS {name}")
    ensure_core(con)
