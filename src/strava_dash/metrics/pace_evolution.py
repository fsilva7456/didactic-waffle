"""Pace evolution marts — the headline "how my pace ranges and pace
distribution have changed over time" feature.

Builds two marts, bucketed by the configurable ``trends.period``
(week | month | quarter | year):

* ``mart_pace_range`` — p10/p25/p50/p75/p90 of a per-activity pace metric per
  period and pace_family. The metric is sport-aware:
    - run  -> avg_pace_min_km (min/km, lower = faster)
    - swim -> min/100m derived from avg_speed_mps
    - ride -> km/h derived from avg_speed_mps
* ``mart_pace_distribution`` — time-in-pace-bucket per period and pace_family,
  plus ``share`` = bucket seconds / total seconds in that period+family
  (shares sum to ~1 per period+family). Sourced from ``pace_histograms``.

Idempotent: DELETE then INSERT, keeping the columns declared in
``schema.MART_DDL``.
"""
from __future__ import annotations

from ..util import load_config

MART_TABLES = ["mart_pace_range", "mart_pace_distribution"]

# pace_families analyzed (excludes 'other').
_FAMILIES = ("run", "swim", "ride")


def _period_exprs(period: str) -> tuple[str, str]:
    """Return (period_label_expr, period_start_expr) SQL for a column over the
    ``activities`` table given the configured trends.period bucket."""
    if period == "week":
        # iso_week is already the Monday of the ISO week.
        return ("strftime(iso_week, '%G-W%V')", "iso_week")
    if period == "month":
        # month is already the first day of the month.
        return ("strftime(month, '%Y-%m')", "month")
    if period == "year":
        return ("CAST(year AS VARCHAR)", "make_date(year, 1, 1)")
    # default: quarter (quarter col is e.g. '2025-Q2'); start = first day of qtr.
    return (
        "quarter",
        "make_date(year, (CAST(substr(quarter, 7, 1) AS INTEGER) - 1) * 3 + 1, 1)",
    )


def _pace_metric_expr() -> str:
    """Per-activity pace metric, sport-aware. Returns SQL over ``activities``.

    run  -> avg_pace_min_km (min/km)
    swim -> min/100m  = (100/avg_speed_mps)/60
    ride -> km/h      = avg_speed_mps * 3.6
    """
    return (
        "CASE pace_family "
        "WHEN 'run'  THEN avg_pace_min_km "
        "WHEN 'swim' THEN CASE WHEN avg_speed_mps > 0 "
        "                      THEN (100.0 / avg_speed_mps) / 60.0 END "
        "WHEN 'ride' THEN CASE WHEN avg_speed_mps > 0 "
        "                      THEN avg_speed_mps * 3.6 END "
        "END"
    )


def build(con) -> None:
    cfg = load_config()
    period = (cfg.get("trends", {}) or {}).get("period", "quarter")
    label_expr, start_expr = _period_exprs(period)
    metric_expr = _pace_metric_expr()
    families = ", ".join(f"'{f}'" for f in _FAMILIES)

    # --- mart_pace_range -----------------------------------------------------
    con.execute("DELETE FROM mart_pace_range")
    con.execute(
        f"""
        INSERT INTO mart_pace_range
            (period, period_start, pace_family, p10, p25, p50, p75, p90,
             n_activities)
        SELECT
            {label_expr}                              AS period,
            {start_expr}                              AS period_start,
            pace_family,
            quantile_cont(m, 0.10)                    AS p10,
            quantile_cont(m, 0.25)                    AS p25,
            quantile_cont(m, 0.50)                    AS p50,
            quantile_cont(m, 0.75)                    AS p75,
            quantile_cont(m, 0.90)                    AS p90,
            count(*)                                  AS n_activities
        FROM (
            SELECT pace_family, iso_week, month, quarter, year,
                   ({metric_expr}) AS m
            FROM activities
            WHERE pace_family IN ({families})
        ) t
        WHERE m IS NOT NULL
        GROUP BY 1, 2, 3
        """
    )

    # --- mart_pace_distribution ---------------------------------------------
    # Join pace_histograms to activities for the period/family, sum seconds per
    # bucket, then compute share against the per-(period, family) total via a
    # window sum so shares add to ~1 within each period+family.
    con.execute("DELETE FROM mart_pace_distribution")
    con.execute(
        f"""
        INSERT INTO mart_pace_distribution
            (period, period_start, pace_family, bucket_idx, bucket_label,
             seconds, share)
        WITH bucketed AS (
            SELECT
                {label_expr}        AS period,
                {start_expr}        AS period_start,
                h.pace_family       AS pace_family,
                h.bucket_idx        AS bucket_idx,
                h.bucket_label      AS bucket_label,
                sum(h.seconds)      AS seconds
            FROM pace_histograms h
            JOIN activities a ON a.id = h.activity_id
            WHERE h.pace_family IN ({families})
            GROUP BY 1, 2, 3, 4, 5
        )
        SELECT
            period, period_start, pace_family, bucket_idx, bucket_label, seconds,
            CASE WHEN sum(seconds) OVER (PARTITION BY period_start, pace_family) > 0
                 THEN seconds
                      / sum(seconds) OVER (PARTITION BY period_start, pace_family)
                 ELSE 0 END                          AS share
        FROM bucketed
        """
    )
