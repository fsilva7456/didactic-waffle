"""PRs / best efforts metric — builds ``mart_prs``.

For every run-family activity we slide a window over its samples (ordered by
``t``) to find, for each standard distance D, the minimum elapsed time covering
at least D meters of cumulative ``distance_m``. The fastest such effort across
all run activities becomes the athlete's best effort (PR) for that distance.

Distances are relative within the window (``distance_m[j] - distance_m[i] >= D``)
so the leading offset of the first sample does not matter.
"""
from __future__ import annotations

import pandas as pd

MART_TABLES = ["mart_prs"]

# Standard running PR distances (label -> meters), longest last for readability.
STD_DISTANCES: list[tuple[str, float]] = [
    ("1k", 1000.0),
    ("5k", 5000.0),
    ("10k", 10000.0),
    ("HM", 21097.0),
]


def _best_effort_seconds(t: list[float], dist: list[float], target_m: float) -> float | None:
    """Minimum elapsed time of a window covering >= target_m meters.

    Two-pointer sweep over cumulative distance. Returns None if the activity
    never covers ``target_m``.
    """
    n = len(t)
    if n < 2:
        return None
    best: float | None = None
    i = 0
    for j in range(n):
        # Advance the left pointer as far as possible while the window still
        # covers the target distance, to minimise elapsed time.
        while i < j and (dist[j] - dist[i + 1]) >= target_m:
            i += 1
        if (dist[j] - dist[i]) >= target_m:
            elapsed = t[j] - t[i]
            if elapsed >= 0 and (best is None or elapsed < best):
                best = elapsed
    return best


def build(con) -> None:
    con.execute("DELETE FROM mart_prs")

    # Pull all run-family samples joined with the activity date in one query,
    # then window per activity in pandas.
    df = con.execute(
        """
        SELECT s.activity_id, s.t, s.distance_m, a.date
        FROM samples s
        JOIN activities a ON a.id = s.activity_id
        WHERE a.pace_family = 'run'
          AND s.distance_m IS NOT NULL
          AND s.t IS NOT NULL
        ORDER BY s.activity_id, s.t
        """
    ).df()
    if df.empty:
        return

    # best per distance label: (best_seconds, activity_id, date)
    best: dict[str, tuple[float, int, object]] = {}

    for activity_id, g in df.groupby("activity_id", sort=False):
        t = g["t"].astype(float).tolist()
        dist = g["distance_m"].astype(float).tolist()
        act_date = g["date"].iloc[0]
        for label, target_m in STD_DISTANCES:
            secs = _best_effort_seconds(t, dist, target_m)
            if secs is None or secs <= 0:
                continue
            cur = best.get(label)
            if cur is None or secs < cur[0]:
                best[label] = (secs, int(activity_id), act_date)

    rows = []
    for label, target_m in STD_DISTANCES:
        if label not in best:
            continue
        secs, activity_id, act_date = best[label]
        pace_min_km = (secs / 60.0) / (target_m / 1000.0)
        rows.append(
            {
                "pace_family": "run",
                "distance_label": label,
                "distance_m": target_m,
                "best_seconds": secs,
                "pace_min_km": pace_min_km,
                "activity_id": activity_id,
                "date": act_date,
            }
        )

    if not rows:
        return

    out = pd.DataFrame(rows)
    con.register("_prs_df", out)
    con.execute(
        """
        INSERT INTO mart_prs
            (pace_family, distance_label, distance_m, best_seconds,
             pace_min_km, activity_id, date)
        SELECT pace_family, distance_label, distance_m, best_seconds,
               pace_min_km, activity_id, date
        FROM _prs_df
        """
    )
    con.unregister("_prs_df")
