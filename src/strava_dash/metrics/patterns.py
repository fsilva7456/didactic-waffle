"""Patterns & gear metrics.

Builds two marts from the CORE `activities` (+ `gear`) tables:

* ``mart_patterns`` — activity habits across four calendar dimensions
  (day-of-week, hour-of-day, season, month), one row per (dimension, bucket,
  sport_type) with counts and totals.
* ``mart_gear`` — per-gear mileage: counts, total distance and the used-date
  span, with the gear name falling back to its id when the gear reference row is
  absent.

Idempotent: each build clears its marts then re-inserts.
"""
from __future__ import annotations

MART_TABLES = ["mart_patterns", "mart_gear"]

# (dimension name, SQL expression yielding the bucket value as text). dow/hour
# are integers cast to VARCHAR; season is already text; month is the first-of-
# month date rendered as text. NULLs are excluded per-dimension below.
_DIMENSIONS = [
    ("dow", "CAST(dow AS VARCHAR)"),
    ("hour", "CAST(hour AS VARCHAR)"),
    ("season", "season"),
    ("month", "CAST(month AS VARCHAR)"),
]


def build(con) -> None:
    # --- mart_patterns -------------------------------------------------------
    con.execute("DELETE FROM mart_patterns")
    selects = []
    for dim, expr in _DIMENSIONS:
        selects.append(f"""
            SELECT
                '{dim}'                       AS dimension,
                {expr}                        AS bucket,
                sport_type                    AS sport,
                count(*)                      AS n_activities,
                COALESCE(sum(distance_km), 0) AS distance_km,
                COALESCE(sum(moving_hours), 0) AS moving_hours
            FROM activities
            WHERE {expr} IS NOT NULL
            GROUP BY {expr}, sport_type
        """)
    union = " UNION ALL ".join(selects)
    con.execute(f"""
        INSERT INTO mart_patterns
            (dimension, bucket, sport, n_activities, distance_km, moving_hours)
        {union}
    """)

    # --- mart_gear -----------------------------------------------------------
    con.execute("DELETE FROM mart_gear")
    con.execute("""
        INSERT INTO mart_gear
            (gear_id, name, type, n_activities, distance_km, first_used, last_used)
        SELECT
            a.gear_id                          AS gear_id,
            COALESCE(g.name, a.gear_id)        AS name,
            g.type                             AS type,
            count(*)                           AS n_activities,
            COALESCE(sum(a.distance_km), 0)    AS distance_km,
            min(a.date)                        AS first_used,
            max(a.date)                        AS last_used
        FROM activities a
        LEFT JOIN gear g ON a.gear_id = g.id
        WHERE a.gear_id IS NOT NULL
        GROUP BY a.gear_id, g.name, g.type
    """)
