"""Tests for the PRs / best-efforts mart against the synthetic fixtures."""
from __future__ import annotations

from strava_dash import schema


def test_mart_prs_has_short_distances(fixture_db):
    con = schema.connect(read_only=True)
    try:
        labels = {r[0] for r in con.execute(
            "SELECT DISTINCT distance_label FROM mart_prs").fetchall()}
    finally:
        con.close()
    assert {"1k", "5k"}.issubset(labels), \
        "fixtures contain runs long enough for 1k and 5k PRs"


def test_mart_prs_values_sane(fixture_db):
    con = schema.connect(read_only=True)
    try:
        rows = con.execute(
            "SELECT distance_label, distance_m, best_seconds, pace_min_km, "
            "activity_id, date FROM mart_prs").fetchall()
    finally:
        con.close()
    assert rows, "mart_prs should have at least one row"
    for label, dist_m, best_seconds, pace, activity_id, date in rows:
        assert best_seconds > 0, f"{label}: best_seconds must be positive"
        assert dist_m > 0
        assert 2.5 <= pace <= 9.0, \
            f"{label}: pace {pace:.2f} min/km outside sane running range"
        assert activity_id is not None
        assert date is not None
        # pace must be internally consistent with seconds/distance
        expected = (best_seconds / 60.0) / (dist_m / 1000.0)
        assert abs(pace - expected) < 1e-6


def test_mart_prs_pace_consistent_with_distance(fixture_db):
    """Longer standard distances should not be faster than the 1k PR."""
    con = schema.connect(read_only=True)
    try:
        rows = dict(con.execute(
            "SELECT distance_label, pace_min_km FROM mart_prs").fetchall())
    finally:
        con.close()
    if "1k" in rows and "5k" in rows:
        assert rows["5k"] >= rows["1k"] - 1e-6, \
            "5k PR pace should not beat the 1k PR pace"
