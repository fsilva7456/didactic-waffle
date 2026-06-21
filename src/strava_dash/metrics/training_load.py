"""Training load metric: CTL (fitness), ATL (fatigue), TSB (form).

Builds `mart_training_load`, one row per calendar day over a continuous date
series from the first to the last activity date (gaps filled with zero load).

Model
-----
* ``daily_load`` = sum of the configured ``load_source`` (default
  ``relative_effort``) over all activities on that calendar date. Days with no
  activity contribute 0.
* ``ctl`` / ``atl`` are exponentially-weighted moving averages of ``daily_load``
  with time constants ``ctl_days`` (42) and ``atl_days`` (7). We use the
  impulse-response form ``ema_t = ema_{t-1} + alpha * (load_t - ema_{t-1})``
  with ``alpha = 1 - exp(-1 / tau)``, seeded at 0 before the first day.
* ``tsb`` = ``ctl - atl`` (training stress balance / form).
"""
from __future__ import annotations

import math

from ..util import load_config

MART_TABLES = ["mart_training_load"]


def build(con) -> None:
    cfg = load_config().get("training_load", {}) or {}
    ctl_days = float(cfg.get("ctl_days", 42))
    atl_days = float(cfg.get("atl_days", 7))
    load_source = cfg.get("load_source", "relative_effort")

    # Guard against an invalid load_source pointing at a non-existent column.
    cols = {r[0] for r in con.execute("DESCRIBE activities").fetchall()}
    if load_source not in cols:
        load_source = "relative_effort"

    con.execute("DELETE FROM mart_training_load")

    span = con.execute("SELECT min(date), max(date) FROM activities").fetchone()
    if not span or span[0] is None:
        return  # no activities -> leave table empty
    dmin, dmax = span[0], span[1]

    # Daily load over a continuous, gap-filled date series. COALESCE the source
    # to 0 so days with activities-but-null-effort still anchor the series.
    rows = con.execute(
        """
        WITH days AS (
            SELECT CAST(d AS DATE) AS date
            FROM range(?::DATE, ?::DATE + INTERVAL 1 DAY, INTERVAL 1 DAY) t(d)
        ),
        daily AS (
            SELECT date, SUM(COALESCE("%s", 0)) AS load
            FROM activities
            WHERE date IS NOT NULL
            GROUP BY date
        )
        SELECT days.date, COALESCE(daily.load, 0) AS daily_load
        FROM days
        LEFT JOIN daily USING (date)
        ORDER BY days.date
        """
        % load_source,
        [dmin, dmax],
    ).fetchall()

    ctl_alpha = 1.0 - math.exp(-1.0 / ctl_days) if ctl_days > 0 else 1.0
    atl_alpha = 1.0 - math.exp(-1.0 / atl_days) if atl_days > 0 else 1.0

    ctl = 0.0
    atl = 0.0
    out = []
    for date, daily_load in rows:
        load = float(daily_load or 0.0)
        ctl += ctl_alpha * (load - ctl)
        atl += atl_alpha * (load - atl)
        tsb = ctl - atl
        out.append((date, load, ctl, atl, tsb))

    if out:
        con.executemany(
            "INSERT INTO mart_training_load "
            "(date, daily_load, ctl, atl, tsb) VALUES (?, ?, ?, ?, ?)",
            out,
        )
