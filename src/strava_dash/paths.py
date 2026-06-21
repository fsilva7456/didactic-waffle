"""Central filesystem locations. Everything is relative to the repo root so the
code works the same in this session, in a worktree, or on a user's laptop."""
from __future__ import annotations

import os
from pathlib import Path

# repo_root/src/strava_dash/paths.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
FIXTURES_DIR = DATA_DIR / "fixtures"
CONFIG_PATH = REPO_ROOT / "config" / "analysis.yaml"

# Subdirectories of a "cache" (either raw/ or fixtures/ share the same layout).
ACTIVITIES_SUBDIR = "activities"   # one {id}.json summary per activity
STREAMS_SUBDIR = "streams"         # one {id}.json stream blob per activity
ATHLETE_FILE = "athlete.json"
GEAR_FILE = "gear.json"
ZONES_FILE = "zones.json"
MANIFEST_FILE = "manifest.json"


def db_path() -> Path:
    """Location of the built DuckDB file. Override with STRAVA_DASH_DB env var
    (handy so tests/e2e can point at a throwaway DB)."""
    override = os.environ.get("STRAVA_DASH_DB")
    return Path(override) if override else DATA_DIR / "strava.duckdb"


def cache_dir(source: str) -> Path:
    """Return the cache directory for a given source: 'raw' or 'fixtures'."""
    if source == "raw":
        return RAW_DIR
    if source == "fixtures":
        return FIXTURES_DIR
    raise ValueError(f"unknown source {source!r}; expected 'raw' or 'fixtures'")
