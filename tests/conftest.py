"""Shared pytest fixtures. Builds a DuckDB from the synthetic fixtures into a
temp file and points the app/transform at it via STRAVA_DASH_DB."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make repo-root packages (e.g. `scripts`) importable from tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("db") / "test.duckdb"
    os.environ["STRAVA_DASH_DB"] = str(db)

    # Ensure fixtures exist (generate if a fresh checkout hasn't yet).
    from strava_dash.paths import FIXTURES_DIR
    if not (FIXTURES_DIR / "activities").exists():
        import scripts.make_fixtures as mk  # type: ignore
        mk.main()

    from strava_dash import metrics, transform
    transform.build(source="fixtures")
    metrics.build_all()
    return db
