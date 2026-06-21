"""Race buildups metric — how training ramped into each race.

Builds two marts from the CORE `activities` table:

* ``mart_race_events`` — one row per detected race event (a triathlon's
  same-day swim/bike/run share one ``race_event_id``). Carries the event date,
  display name, optional A/B/C priority (from ``config.races.pinned_events`` when
  a pinned event matches the date), the set of sports contested, and the leg
  count.
* ``mart_race_buildup`` — for every event, the N-week training block leading up
  to it (``config.buildup.weeks_before``, default 16). Each row is one
  ``(event, weeks_to_race, sport)`` cell aggregating ALL training that fell in
  that calendar week relative to the race: weekly distance/hours/counts plus, for
  runs, the long-run distance and mean run pace. ``weeks_to_race`` is 0 for the
  race week, 1 for the week before, etc.; ``week_start`` is that week's Monday.

The two together drive the "Race Buildups" page, which overlays buildups across
races aligned on ``weeks_to_race`` (volume ramp, long-run progression, pace).
"""
from __future__ import annotations

from .. import schema
from ..util import load_config

MART_TABLES = ["mart_race_events", "mart_race_buildup"]


def build(con) -> None:
    cfg = load_config()
    buildup = cfg.get("buildup", {}) or {}
    weeks_before = int(buildup.get("weeks_before", 16) or 16)

    pinned = (cfg.get("races", {}) or {}).get("pinned_events") or []
    # Map race date (ISO string) -> priority for any pinned event.
    pin_priority = {
        str(p.get("date")): p.get("priority")
        for p in pinned
        if p.get("date") is not None
    }

    schema.ensure_marts(con)

    # --- mart_race_events ----------------------------------------------------
    con.execute("DELETE FROM mart_race_events")
    events = con.execute(
        """
        SELECT
            race_event_id                          AS event_id,
            min(date)                              AS date,
            any_value(race_name)                   AS name,
            string_agg(DISTINCT sport_type, ', ' ORDER BY sport_type) AS sports,
            count(*)                               AS n_activities
        FROM activities
        WHERE race_event_id IS NOT NULL
        GROUP BY race_event_id
        ORDER BY date
        """
    ).fetchall()

    for event_id, date, name, sports, n_activities in events:
        priority = pin_priority.get(date.isoformat()) if date is not None else None
        con.execute(
            "INSERT INTO mart_race_events "
            "(event_id, date, name, priority, sports, n_activities) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [event_id, date, name, priority, sports, n_activities],
        )

    # --- mart_race_buildup ---------------------------------------------------
    con.execute("DELETE FROM mart_race_buildup")
    # For each race event we know its Monday (the Monday of the race week). Any
    # activity's iso_week is the Monday of its own week, so the integer number of
    # weeks before the race is just the week-difference. We aggregate per
    # (event, weeks_to_race, sport) and keep only the buildup window [0, N].
    con.execute(
        """
        INSERT INTO mart_race_buildup (
            event_id, race_name, weeks_to_race, week_start, sport,
            distance_km, moving_hours, long_run_km, avg_pace_min_km, n_activities
        )
        WITH events AS (
            SELECT
                race_event_id                                   AS event_id,
                any_value(race_name)                            AS race_name,
                CAST(date_trunc('week', min(date)) AS DATE)     AS race_monday
            FROM activities
            WHERE race_event_id IS NOT NULL
            GROUP BY race_event_id
        ),
        joined AS (
            SELECT
                e.event_id,
                e.race_name,
                CAST(date_diff('day', a.iso_week, e.race_monday) / 7 AS INTEGER)
                    AS weeks_to_race,
                a.iso_week AS week_start,
                a.sport_type AS sport,
                a.distance_km,
                a.moving_hours,
                a.pace_family,
                a.avg_pace_min_km
            FROM activities a
            JOIN events e
              ON a.iso_week <= e.race_monday
             AND date_diff('day', a.iso_week, e.race_monday) / 7 <= ?
        )
        SELECT
            event_id,
            race_name,
            weeks_to_race,
            week_start,
            sport,
            sum(distance_km)                                        AS distance_km,
            sum(moving_hours)                                       AS moving_hours,
            max(CASE WHEN sport = 'Run' THEN distance_km END)       AS long_run_km,
            avg(CASE WHEN pace_family = 'run' THEN avg_pace_min_km END)
                                                                    AS avg_pace_min_km,
            count(*)                                                AS n_activities
        FROM joined
        GROUP BY event_id, race_name, weeks_to_race, week_start, sport
        ORDER BY event_id, weeks_to_race, sport
        """,
        [weeks_before],
    )
