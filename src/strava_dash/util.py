"""Shared helpers: config loading, unit conversions, sport classification.

These are deliberately dependency-light (no DuckDB) so every layer — ingest,
transform, metrics, app — can import them without circulars.
"""
from __future__ import annotations

import functools
from typing import Any

import yaml

from .paths import CONFIG_PATH


@functools.lru_cache(maxsize=1)
def load_config(path: str | None = None) -> dict[str, Any]:
    """Load config/analysis.yaml once. Pass an explicit path in tests."""
    p = path or str(CONFIG_PATH)
    with open(p, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# --- unit conversions --------------------------------------------------------

def mps_to_pace_min_per_km(speed_mps: float) -> float | None:
    """Convert m/s to running pace in minutes per km. None if not moving."""
    if not speed_mps or speed_mps <= 0:
        return None
    return (1000.0 / speed_mps) / 60.0


def mps_to_pace_min_per_100m(speed_mps: float) -> float | None:
    """Convert m/s to swim pace in minutes per 100m."""
    if not speed_mps or speed_mps <= 0:
        return None
    return (100.0 / speed_mps) / 60.0


def mps_to_kmh(speed_mps: float) -> float | None:
    if speed_mps is None:
        return None
    return speed_mps * 3.6


def pace_min_per_km_to_str(pace: float | None) -> str:
    """Format a min/km float as M:SS."""
    if pace is None:
        return "—"
    minutes = int(pace)
    seconds = int(round((pace - minutes) * 60))
    if seconds == 60:
        minutes, seconds = minutes + 1, 0
    return f"{minutes}:{seconds:02d}"


# --- sport classification ----------------------------------------------------

def pace_family(sport_type: str, config: dict[str, Any] | None = None) -> str:
    """Classify a Strava sport_type into a pace family used for analysis:
    'run' (min/km), 'swim' (min/100m), 'ride' (km/h) or 'other'."""
    cfg = config or load_config()
    s = cfg.get("sports", {})
    if sport_type in s.get("pace_based", []):
        return "run"
    if sport_type in s.get("swim_based", []):
        return "swim"
    if sport_type in s.get("speed_based", []):
        return "ride"
    return "other"
