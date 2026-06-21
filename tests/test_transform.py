"""Core transform contract tests against the synthetic fixtures."""
from __future__ import annotations

from strava_dash import schema


def test_core_tables_populated(fixture_db):
    con = schema.connect(read_only=True)
    try:
        n_act = con.execute("SELECT count(*) FROM activities").fetchone()[0]
        n_hist = con.execute("SELECT count(*) FROM pace_histograms").fetchone()[0]
        n_samp = con.execute("SELECT count(*) FROM samples").fetchone()[0]
    finally:
        con.close()
    assert n_act > 50, "expected a substantial fixture history"
    assert n_hist > 0, "pace histograms should be built from streams"
    assert n_samp > 0


def test_sports_and_pace_family(fixture_db):
    con = schema.connect(read_only=True)
    try:
        fams = {r[0] for r in con.execute(
            "SELECT DISTINCT pace_family FROM activities").fetchall()}
        run_pace = con.execute(
            "SELECT count(*) FROM activities "
            "WHERE pace_family='run' AND avg_pace_min_km IS NOT NULL").fetchone()[0]
    finally:
        con.close()
    assert {"run", "ride", "swim"}.issubset(fams)
    assert run_pace > 0


def test_races_detected_and_grouped(fixture_db):
    con = schema.connect(read_only=True)
    try:
        n_race = con.execute(
            "SELECT count(*) FROM activities WHERE is_race").fetchone()[0]
        n_events = con.execute(
            "SELECT count(DISTINCT race_event_id) FROM activities "
            "WHERE race_event_id IS NOT NULL").fetchone()[0]
    finally:
        con.close()
    assert n_race >= 3, "fixtures contain triathlon race legs"
    assert n_events >= 3, "race legs on a day should group into one event"


def test_marts_exist(fixture_db):
    con = schema.connect(read_only=True)
    try:
        for tbl in schema.MART_DDL:
            con.execute(f"SELECT count(*) FROM {tbl}").fetchone()
    finally:
        con.close()
