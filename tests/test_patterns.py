"""Tests for the patterns & gear marts."""
from __future__ import annotations

from strava_dash import schema


def test_mart_patterns_dimensions(fixture_db):
    con = schema.connect(read_only=True)
    try:
        dims = {r[0] for r in con.execute(
            "SELECT DISTINCT dimension FROM mart_patterns").fetchall()}
        assert {"dow", "hour", "season", "month"} <= dims

        # Every dimension has at least one bucket with a positive count.
        for dim in ("dow", "hour", "season", "month"):
            n = con.execute(
                "SELECT count(*) FROM mart_patterns "
                "WHERE dimension = ? AND n_activities > 0", [dim]).fetchone()[0]
            assert n > 0, f"no positive-count rows for dimension {dim}"

        # All counts are positive; distance/hours non-negative.
        bad = con.execute(
            "SELECT count(*) FROM mart_patterns "
            "WHERE n_activities <= 0 OR distance_km < 0 OR moving_hours < 0"
        ).fetchone()[0]
        assert bad == 0

        # dow buckets are within 0..6.
        dow_buckets = {r[0] for r in con.execute(
            "SELECT DISTINCT bucket FROM mart_patterns WHERE dimension='dow'"
        ).fetchall()}
        assert dow_buckets <= {str(i) for i in range(7)}
    finally:
        con.close()


def test_mart_gear_rows(fixture_db):
    con = schema.connect(read_only=True)
    try:
        total, with_dist = con.execute(
            "SELECT count(*), count(*) FILTER (WHERE distance_km > 0) "
            "FROM mart_gear").fetchone()
        assert total > 0
        assert with_dist > 0

        # No null gear_id should ever be aggregated; name falls back to id.
        nulls = con.execute(
            "SELECT count(*) FROM mart_gear WHERE gear_id IS NULL").fetchone()[0]
        assert nulls == 0
        missing_name = con.execute(
            "SELECT count(*) FROM mart_gear WHERE name IS NULL").fetchone()[0]
        assert missing_name == 0
    finally:
        con.close()
