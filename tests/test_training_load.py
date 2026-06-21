"""Contract tests for the training load mart (CTL/ATL/TSB)."""
from __future__ import annotations

from strava_dash import schema


def test_training_load_has_rows(fixture_db):
    con = schema.connect(read_only=True)
    try:
        n = con.execute("SELECT count(*) FROM mart_training_load").fetchone()[0]
    finally:
        con.close()
    assert n > 0, "mart_training_load should be populated from the fixtures"


def test_dates_are_continuous(fixture_db):
    con = schema.connect(read_only=True)
    try:
        n_rows, dmin, dmax, n_distinct = con.execute(
            "SELECT count(*), min(date), max(date), count(DISTINCT date) "
            "FROM mart_training_load"
        ).fetchone()
    finally:
        con.close()
    span_days = (dmax - dmin).days
    # Continuous daily series: one row per day, inclusive of both endpoints.
    assert n_rows == span_days + 1, "expected a gap-free daily date series"
    assert n_distinct == n_rows, "dates should be unique (one row per day)"


def test_ctl_non_negative_and_not_all_zero(fixture_db):
    con = schema.connect(read_only=True)
    try:
        min_ctl, max_ctl = con.execute(
            "SELECT min(ctl), max(ctl) FROM mart_training_load"
        ).fetchone()
    finally:
        con.close()
    assert min_ctl >= -1e-9, "CTL should be non-negative"
    assert max_ctl > 0, "CTL should rise above zero with training load"


def test_tsb_equals_ctl_minus_atl(fixture_db):
    con = schema.connect(read_only=True)
    try:
        max_err = con.execute(
            "SELECT max(abs(tsb - (ctl - atl))) FROM mart_training_load"
        ).fetchone()[0]
    finally:
        con.close()
    assert max_err is not None
    assert max_err < 1e-9, "tsb must equal ctl - atl"
