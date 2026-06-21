"""Volume metric — weekly and monthly training volume per sport.

Builds `mart_volume`: for each period (week | month) and each `period_start`
it emits one row per `sport_type` plus an 'ALL' rollup (sport='ALL',
pace_family='mixed'). Volume is distance (km), moving time (hours), activity
count and elevation gain.

Periods:
  * week  -> period_start = activities.iso_week (Monday of the ISO week)
  * month -> period_start = activities.month    (first day of the month)
"""
from __future__ import annotations

MART_TABLES = ["mart_volume"]


def build(con) -> None:
    con.execute("DELETE FROM mart_volume")

    # One INSERT per (period grain) x (per-sport | ALL rollup). DuckDB's
    # GROUPING SETS gives us both the per-sport rows and the rollup in a single
    # scan: the rollup row has sport_type NULL, which we map to 'ALL'/'mixed'.
    for period, col in (("week", "iso_week"), ("month", "month")):
        con.execute(
            f"""
            INSERT INTO mart_volume
                (period, period_start, sport, pace_family, distance_km,
                 moving_hours, n_activities, elevation_gain)
            SELECT
                '{period}'                              AS period,
                {col}                                   AS period_start,
                COALESCE(sport_type, 'ALL')             AS sport,
                CASE WHEN sport_type IS NULL THEN 'mixed'
                     ELSE any_value(pace_family) END    AS pace_family,
                SUM(distance_km)                        AS distance_km,
                SUM(moving_hours)                       AS moving_hours,
                COUNT(*)                                AS n_activities,
                SUM(COALESCE(elevation_gain, 0))        AS elevation_gain
            FROM activities
            WHERE {col} IS NOT NULL
            GROUP BY GROUPING SETS (({col}, sport_type), ({col}))
            """
        )
