"""Race buildup mart contract tests against the synthetic fixtures.

Fixtures contain 3 triathlon races, each with a rising 16-week buildup.
"""
from __future__ import annotations

from strava_dash import schema


def test_race_events_detected(fixture_db):
    con = schema.connect(read_only=True)
    try:
        rows = con.execute(
            "SELECT event_id, date, name, sports, n_activities FROM mart_race_events"
        ).fetchall()
    finally:
        con.close()
    assert len(rows) >= 3, "fixtures contain at least 3 race events"
    # Each triathlon event groups its same-day legs (>1 activity, multiple sports).
    for event_id, date, name, sports, n_activities in rows:
        assert event_id, "event_id must be populated"
        assert date is not None
        assert n_activities >= 1
        assert sports, "sports set should be comma-joined sport types"


def test_buildup_spans_range_and_has_volume(fixture_db):
    con = schema.connect(read_only=True)
    try:
        n_rows = con.execute("SELECT count(*) FROM mart_race_buildup").fetchone()[0]
        wmin, wmax = con.execute(
            "SELECT min(weeks_to_race), max(weeks_to_race) FROM mart_race_buildup"
        ).fetchone()
        # Every event should reach back a meaningful number of weeks.
        per_event_max = con.execute(
            "SELECT event_id, max(weeks_to_race) FROM mart_race_buildup "
            "GROUP BY event_id"
        ).fetchall()
        # Buildup weeks (not the race week itself) should carry positive volume.
        pos_dist = con.execute(
            "SELECT count(*) FROM mart_race_buildup "
            "WHERE weeks_to_race > 0 AND distance_km > 0"
        ).fetchone()[0]
        out_of_window = con.execute(
            "SELECT count(*) FROM mart_race_buildup "
            "WHERE weeks_to_race < 0 OR weeks_to_race > 16"
        ).fetchone()[0]
    finally:
        con.close()

    assert n_rows > 0, "buildup mart should be populated"
    assert wmin == 0, "race week is weeks_to_race = 0"
    assert wmax >= 8, "buildup should span a meaningful range of weeks"
    assert len(per_event_max) >= 3
    for _event_id, ev_max in per_event_max:
        assert ev_max >= 8, "each race should have a multi-week buildup block"
    assert pos_dist > 0, "buildup weeks should carry training volume"
    assert out_of_window == 0, "weeks_to_race must stay within [0, weeks_before]"


def test_long_run_only_for_runs(fixture_db):
    con = schema.connect(read_only=True)
    try:
        # long_run_km is the max single Run distance that week -> null for
        # non-Run sports, populated for Run rows.
        bad = con.execute(
            "SELECT count(*) FROM mart_race_buildup "
            "WHERE sport <> 'Run' AND long_run_km IS NOT NULL"
        ).fetchone()[0]
        run_long = con.execute(
            "SELECT count(*) FROM mart_race_buildup "
            "WHERE sport = 'Run' AND long_run_km > 0"
        ).fetchone()[0]
    finally:
        con.close()
    assert bad == 0, "long_run_km should only be set for Run rows"
    assert run_long > 0, "Run buildup weeks should have a long run"
