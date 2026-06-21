"""Tests for the volume metric (`mart_volume`)."""
from __future__ import annotations


def _con():
    from strava_dash import schema
    return schema.connect(read_only=True)


def test_mart_volume_has_week_and_month_rows(fixture_db):
    con = _con()
    try:
        periods = {r[0] for r in
                   con.execute("SELECT DISTINCT period FROM mart_volume").fetchall()}
    finally:
        con.close()
    assert "week" in periods
    assert "month" in periods


def test_mart_volume_has_all_rollup(fixture_db):
    con = _con()
    try:
        n_all = con.execute(
            "SELECT count(*) FROM mart_volume WHERE sport = 'ALL'").fetchone()[0]
        # Rollup rows use pace_family='mixed'.
        n_mixed = con.execute(
            "SELECT count(*) FROM mart_volume "
            "WHERE sport = 'ALL' AND pace_family = 'mixed'").fetchone()[0]
    finally:
        con.close()
    assert n_all > 0
    assert n_all == n_mixed


def test_mart_volume_distance_positive(fixture_db):
    con = _con()
    try:
        total = con.execute(
            "SELECT sum(distance_km) FROM mart_volume").fetchone()[0]
    finally:
        con.close()
    assert total is not None and total > 0


def test_all_rollup_equals_sum_of_sports(fixture_db):
    """For each period/period_start the 'ALL' row equals the per-sport sum."""
    con = _con()
    try:
        mismatches = con.execute(
            """
            WITH agg AS (
                SELECT period, period_start,
                    sum(CASE WHEN sport = 'ALL' THEN distance_km END) AS all_km,
                    sum(CASE WHEN sport <> 'ALL' THEN distance_km END) AS sum_km,
                    sum(CASE WHEN sport = 'ALL' THEN n_activities END) AS all_n,
                    sum(CASE WHEN sport <> 'ALL' THEN n_activities END) AS sum_n
                FROM mart_volume
                GROUP BY period, period_start
            )
            SELECT count(*) FROM agg
            WHERE abs(all_km - sum_km) > 1e-6 OR all_n <> sum_n
            """
        ).fetchone()[0]
    finally:
        con.close()
    assert mismatches == 0
