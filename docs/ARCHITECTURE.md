# Architecture

A four-layer pipeline. Each layer is a pure function over the previous layer's
output, so the whole thing rebuilds offline and is testable against synthetic
fixtures.

```
ingest    data/raw/{activities,streams}/*.json   (Strava MCP, resumable)
   |
transform CORE DuckDB tables: activities, samples, pace_histograms, athlete, gear
   |
metrics   MART tables: mart_volume, mart_pace_range, mart_pace_distribution,
   |        mart_race_events, mart_race_buildup, mart_training_load, mart_prs,
   |        mart_patterns, mart_gear
   |
app       Streamlit pages reading the marts
```

## Why this shape

- **Pull once, analyze forever.** Strava is rate-limited and per-activity streams
  are the expensive call. The ingester caches each activity's JSON exactly once
  and is resumable via a manifest; all analysis runs offline against the cache.
- **Schema as the contract.** Metric modules *write* mart tables; dashboard pages
  *read* them. They are decoupled through `schema.MART_DDL` — not Python imports —
  so they can be built and merged independently. A not-yet-built metric just
  yields an empty table (`schema.ensure_marts` creates them), and the dashboard
  degrades gracefully.
- **Sport-aware.** `pace_family` maps each `sport_type` to run (min/km), swim
  (min/100m), ride (km/h) or other. Pace bins live in `config/analysis.yaml`.

## CORE tables (built by `transform.py`)

| Table | Grain | Notes |
|---|---|---|
| `activities` | 1 row / activity | derived calendar cols, `pace_family`, `avg_pace_min_km`, `is_race`, `race_event_id` |
| `samples` | 1 row / stream sample | downsampled time series for deep dives |
| `pace_histograms` | activity × pace bucket | time-in-bucket; the compact basis for distribution analysis |
| `athlete`, `gear` | reference | from profile / gear endpoints |

## MART tables (built by `metrics/*.py`)

Declared in `schema.MART_DDL`. Highlights tied to the stated requirements:

- **`mart_volume`** — weekly/monthly distance, moving hours, counts per sport.
- **`mart_pace_range`** — p10/p25/p50/p75/p90 pace per period (pace *ranges* over time).
- **`mart_pace_distribution`** — time-in-pace-bucket per period + share (how the
  *distribution* shifts over time).
- **`mart_race_events`** / **`mart_race_buildup`** — detected races and the
  N-week buildup block before each (volume ramp, long-run progression, paces).
- **`mart_training_load`** — CTL/ATL/TSB.
- **`mart_prs`**, **`mart_patterns`**, **`mart_gear`** — PRs, habits, gear mileage.

## Config (`config/analysis.yaml`)

Captures the user's analysis requirements without code changes: pace/speed bins,
race-detection patterns, buildup window length, trend period, training-load
constants. Loaded by `util.load_config()`.

## Extending

### Add a metric
Drop a module in `src/strava_dash/metrics/`:

```python
# src/strava_dash/metrics/my_metric.py
MART_TABLES = ["mart_xxx"]            # must be declared in schema.MART_DDL

def build(con) -> None:
    con.execute("DELETE FROM mart_xxx")           # idempotent
    con.execute("INSERT INTO mart_xxx SELECT ... FROM activities ...")
```

`metrics.build_all()` discovers it automatically (no central registration), so
units stay independently mergeable. If you need a brand-new mart table, add its
DDL to `schema.MART_DDL` in the same module's work.

### Add a dashboard page
Drop a file in `src/strava_dash/app/pages/NN_Name.py` and read marts via the
shared helpers:

```python
import streamlit as st
from strava_dash.app._shared import get_con, sidebar_filters, mart

con = get_con()
flt = sidebar_filters(con)
df = mart(con, "mart_volume")
# ... plotly charts ...
```

Do not modify `app/_shared.py` (shared, complete) so pages don't collide.

## Ingestion (real data)

The Strava MCP is bound to an interactive Claude session (it is not available to
background/worktree agents). The ingester:

1. Pages `list_activities` across the sync window → `data/raw/activities/<id>.json`.
2. For each uncached activity, `get_activity_streams` → `data/raw/streams/<id>.json`.
3. Records progress in `data/manifest.json` so it is **resumable** and respects
   Strava's rate limits (200 req / 15 min, 2000 / day) across runs.

Fixtures (`scripts/make_fixtures.py`) mimic this exact on-disk shape, so every
downstream layer is developed and tested without touching the live API.

## Testing / e2e

- `tests/conftest.py` builds a DuckDB from the seeded fixtures into a temp file.
- `test_transform.py` asserts the CORE contract (tables populated, sports
  classified, races grouped).
- `test_app_smoke.py` renders the Streamlit app + every page headlessly via
  `streamlit.testing.v1.AppTest` and asserts no exception — the e2e recipe for
  dashboard units.
