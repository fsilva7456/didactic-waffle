# Strava Training Dashboard

Local, **private** dashboard for analyzing your Strava training over time —
weekly/monthly **volume**, **pace ranges**, how your **pace distribution** has
shifted, **race buildups**, training load, PRs, and habits. Everything runs on
your machine; your data never leaves it.

## Quick start

```bash
make install        # create env / install package (or: pip install -e ".[dev]")
make fixtures-db    # build a demo DB from synthetic data (no Strava needed)
make dashboard      # launch the Streamlit app
```

To use **your** data instead of the demo fixtures, harvest from Strava (see
`docs/ARCHITECTURE.md` → Ingestion), then:

```bash
make build          # transform data/raw/ -> DuckDB, then build marts
make dashboard
```

## Pipeline

```
ingest  ->  transform  ->  metrics  ->  dashboard
(Strava     (raw JSON      (DuckDB       (Streamlit
 MCP ->      -> DuckDB       marts)        pages)
 data/raw)   core tables)
```

- **ingest** — harvest activities + per-second streams into `data/raw/`.
- **transform** (`strava_dash/transform.py`) — normalize the cache into CORE
  DuckDB tables (`activities`, `samples`, `pace_histograms`).
- **metrics** (`strava_dash/metrics/*.py`) — build analytics MART tables.
- **app** (`strava_dash/app/`) — Streamlit dashboard reading the marts.

See `docs/ARCHITECTURE.md` for the full design, the table contracts, and how to
add a metric or a dashboard page.

## Commands

| Command | Description |
|---|---|
| `make fixtures` | (Re)generate the synthetic demo dataset |
| `make fixtures-db` | Build the DuckDB from fixtures |
| `make build` | Build the DuckDB from your real harvested cache |
| `make marts` | Rebuild analytics marts only |
| `make dashboard` | Launch the Streamlit app |
| `make test` | Run the test suite |
