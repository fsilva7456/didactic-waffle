.PHONY: install fixtures fixtures-db build marts dashboard test lint clean

# Install the package + dev deps (editable).
install:
	pip install -e ".[dev]"

# (Re)generate the synthetic fixture dataset under data/fixtures/.
fixtures:
	python scripts/make_fixtures.py

# Build a DuckDB database from the synthetic fixtures (used by tests & e2e).
# Regenerates the fixtures first so a fresh checkout works with no extra steps.
fixtures-db: fixtures
	python -m strava_dash.cli build --source fixtures

# Build the DuckDB database from the real harvested cache (data/raw/).
build:
	python -m strava_dash.cli build --source raw

# Rebuild all analytics marts from the current DuckDB tables.
marts:
	python -m strava_dash.cli marts

# Launch the local Streamlit dashboard.
dashboard:
	streamlit run src/strava_dash/app/Home.py

test:
	pytest -q

lint:
	ruff check src tests

clean:
	rm -f data/strava.duckdb
	rm -rf .pytest_cache
