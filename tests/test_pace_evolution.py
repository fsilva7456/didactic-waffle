"""Tests for the pace_evolution marts (mart_pace_range, mart_pace_distribution).

Uses the session-scoped ``fixture_db`` fixture which builds the CORE tables and
runs every metric's build(), so by the time these run the marts are populated.
"""
from __future__ import annotations

import pytest

from strava_dash import schema


@pytest.fixture(scope="module")
def con(fixture_db):
    c = schema.connect(read_only=True)
    yield c
    c.close()


def test_marts_populated(con):
    n_range = con.execute("SELECT count(*) FROM mart_pace_range").fetchone()[0]
    n_dist = con.execute("SELECT count(*) FROM mart_pace_distribution").fetchone()[0]
    assert n_range > 0, "mart_pace_range should be populated"
    assert n_dist > 0, "mart_pace_distribution should be populated"


def test_distribution_shares_sum_to_one(con):
    """Within each (period, pace_family), the bucket shares should sum to ~1."""
    rows = con.execute(
        """
        SELECT period, pace_family, sum(share) AS total
        FROM mart_pace_distribution
        GROUP BY 1, 2
        """
    ).fetchall()
    assert rows, "expected at least one (period, pace_family) group"
    for period, fam, total in rows:
        assert total == pytest.approx(1.0, abs=1e-6), (
            f"shares for ({period}, {fam}) sum to {total}, expected ~1.0"
        )


def test_run_p50_in_plausible_range(con):
    """Run-family median pace (min/km) should be in a realistic ~3–9 range."""
    rows = con.execute(
        "SELECT period, p50 FROM mart_pace_range WHERE pace_family = 'run'"
    ).fetchall()
    assert rows, "expected run-family rows in mart_pace_range"
    for period, p50 in rows:
        assert 3.0 <= p50 <= 9.0, f"run p50 for {period} = {p50}, expected 3–9 min/km"


def test_percentiles_are_ordered(con):
    """Percentiles should be monotonically non-decreasing within each row."""
    rows = con.execute(
        "SELECT p10, p25, p50, p75, p90 FROM mart_pace_range"
    ).fetchall()
    assert rows
    for p10, p25, p50, p75, p90 in rows:
        assert p10 <= p25 <= p50 <= p75 <= p90


def test_expected_families_present(con):
    fams = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT pace_family FROM mart_pace_range"
        ).fetchall()
    }
    # Fixtures include run, swim and ride activities.
    assert {"run", "swim", "ride"} <= fams
