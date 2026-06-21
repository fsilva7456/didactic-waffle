"""Transform the raw/fixtures JSON cache into the DuckDB CORE tables.

Idempotent: drops & rebuilds the core tables from whatever is on disk. All
analysis is done downstream against these tables, so this can run offline and is
the unit under test for the fixtures-based e2e recipe.

Canonical cache layout (shared by the real harvester and the fixtures):
    <cache>/activities/<id>.json   # one activity summary (list_activities item
                                     # shape, optionally enriched with detail
                                     # fields: workout_type, average_heartrate)
    <cache>/streams/<id>.json      # {"activity_id": id, "streams": {<name>: [...]}}
    <cache>/athlete.json
    <cache>/gear.json
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from . import schema
from .paths import (
    ACTIVITIES_SUBDIR,
    ATHLETE_FILE,
    GEAR_FILE,
    STREAMS_SUBDIR,
    cache_dir,
)
from .util import (
    load_config,
    mps_to_kmh,
    mps_to_pace_min_per_100m,
    mps_to_pace_min_per_km,
    pace_family,
)

_SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring",
            5: "Spring", 6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall",
            10: "Fall", 11: "Fall"}


# --- cache reading -----------------------------------------------------------

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _iter_activity_files(cache: Path):
    d = cache / ACTIVITIES_SUBDIR
    if not d.exists():
        return
    for p in sorted(d.glob("*.json")):
        yield p


def _stream_values(stream: Any) -> list:
    """Accept both [..] and Strava-native {"data": [..]} stream shapes."""
    if stream is None:
        return []
    if isinstance(stream, dict):
        return stream.get("data") or []
    return list(stream)


# --- derivations -------------------------------------------------------------

def _parse_start(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_race(name: str, workout_type: int | None, cfg: dict) -> bool:
    rc = cfg.get("races", {})
    name = name or ""
    for pat in rc.get("name_patterns", []):
        if re.search(pat, name, re.IGNORECASE):
            return True
    if rc.get("use_workout_type") and workout_type in (1, 11):
        return True
    return False


def _race_name(name: str) -> str:
    # Strip the leg suffix from triathlon legs: "X - Run" / "X - Ride (...)".
    base = re.split(r"\s[-–]\s(Run|Ride|Swim|Bike)\b", name)[0]
    return base.strip() or name


def _pace_edges(pace_fam: str, cfg: dict) -> tuple[list[float], str]:
    if pace_fam == "run":
        b = cfg["pace_bins_run"]
        return b["edges"], "min/km"
    if pace_fam == "swim":
        b = cfg["pace_bins_swim"]
        return b["edges"], "min/100m"
    if pace_fam == "ride":
        b = cfg["speed_bins_ride"]
        return b["edges"], "km/h"
    return [], ""


def _bucket(value: float, edges: list[float]) -> int:
    """Index of the bucket value falls into. 0 = below first edge,
    len(edges) = above last edge."""
    idx = 0
    for e in edges:
        if value < e:
            return idx
        idx += 1
    return idx


def _bucket_label(idx: int, edges: list[float], unit: str, pace_fam: str) -> str:
    if pace_fam in ("run", "swim"):  # smaller pace number = faster
        if idx == 0:
            return f"<{edges[0]:g} {unit}"
        if idx >= len(edges):
            return f"{edges[-1]:g}+ {unit}"
        return f"{edges[idx - 1]:g}–{edges[idx]:g} {unit}"
    # speed: larger = faster
    if idx == 0:
        return f"<{edges[0]:g} {unit}"
    if idx >= len(edges):
        return f"{edges[-1]:g}+ {unit}"
    return f"{edges[idx - 1]:g}–{edges[idx]:g} {unit}"


# --- core builders -----------------------------------------------------------

def _build_activity_row(raw: dict, cfg: dict) -> dict:
    summ = raw.get("summary", raw)  # tolerate flat or nested
    start = _parse_start(raw.get("start_local"))
    sport = raw.get("sport_type") or raw.get("type") or "Unknown"
    fam = pace_family(sport, cfg)
    dist_m = float(summ.get("distance") or 0)
    moving_s = int(summ.get("moving_time") or 0)
    avg_speed = float(summ.get("avg_speed") or summ.get("average_speed") or 0)
    wtype = raw.get("workout_type")
    name = raw.get("name") or ""
    is_race = _is_race(name, wtype, cfg)

    avg_pace = mps_to_pace_min_per_km(avg_speed) if fam == "run" else None

    row = {
        "id": int(raw["id"]),
        "name": name,
        "sport_type": sport,
        "pace_family": fam,
        "start_local": start,
        "date": start.date() if start else None,
        "year": start.year if start else None,
        "month": start.replace(day=1).date() if start else None,
        "quarter": f"{start.year}-Q{(start.month - 1) // 3 + 1}" if start else None,
        "iso_week": (start.date() - timedelta(days=start.weekday()))
        if start else None,
        "season": _SEASONS.get(start.month) if start else None,
        "dow": start.weekday() if start else None,
        "hour": start.hour if start else None,
        "distance_m": dist_m,
        "distance_km": dist_m / 1000.0,
        "moving_time_s": moving_s,
        "elapsed_time_s": int(summ.get("elapsed_time") or 0),
        "moving_hours": moving_s / 3600.0,
        "avg_speed_mps": avg_speed,
        "max_speed_mps": float(summ.get("max_speed") or 0),
        "avg_pace_min_km": avg_pace,
        "elevation_gain": float(summ.get("elevation_gain") or 0),
        "avg_hr": summ.get("average_heartrate") or summ.get("avg_hr"),
        "max_hr": summ.get("max_heartrate") or summ.get("max_hr"),
        "avg_cadence": summ.get("avg_cadence"),
        "relative_effort": summ.get("relative_effort"),
        "calories": summ.get("total_calories") or summ.get("calories"),
        "gear_id": raw.get("gear_id"),
        "workout_type": wtype,
        "is_race": is_race,
        "race_event_id": None,
        "race_name": _race_name(name) if is_race else None,
        "has_streams": False,
    }
    return row


def _assign_race_events(activities: list[dict], cfg: dict) -> None:
    """Group same-day race legs into one event id (in place)."""
    races = [a for a in activities if a["is_race"] and a["date"]]
    for a in races:
        slug = re.sub(r"[^a-z0-9]+", "-", (a["race_name"] or "race").lower()).strip("-")
        a["race_event_id"] = f"{a['date'].isoformat()}-{slug}"


def _build_streams(raw_streams: dict, fam: str, edges: list[float], unit: str,
                   activity_id: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    streams = raw_streams.get("streams", raw_streams)
    t = _stream_values(streams.get("time"))
    if not t:
        return pd.DataFrame(), pd.DataFrame()
    speed = _stream_values(streams.get("velocity_smooth")) or _stream_values(
        streams.get("speed"))
    dist = _stream_values(streams.get("distance"))
    hr = _stream_values(streams.get("heartrate"))
    alt = _stream_values(streams.get("altitude"))
    cad = _stream_values(streams.get("cadence"))
    moving = _stream_values(streams.get("moving"))
    n = len(t)

    def at(seq, i, default=None):
        return seq[i] if i < len(seq) else default

    sample_rows = []
    hist: dict[int, float] = {}
    for i in range(n):
        ti = t[i]
        sp = at(speed, i, 0) or 0
        mv = at(moving, i, sp > 0.3)
        dt = (t[i + 1] - ti) if i + 1 < n else (ti - t[i - 1] if i > 0 else 1)
        dt = max(dt, 0)
        pace_km = mps_to_pace_min_per_km(sp) if fam == "run" else None
        sample_rows.append({
            "activity_id": activity_id, "t": ti, "distance_m": at(dist, i),
            "speed_mps": sp, "pace_min_km": pace_km, "heartrate": at(hr, i),
            "altitude": at(alt, i), "cadence": at(cad, i), "moving": bool(mv),
        })
        if mv and sp and sp > 0 and edges:
            if fam == "run":
                metric = mps_to_pace_min_per_km(sp)
            elif fam == "swim":
                metric = mps_to_pace_min_per_100m(sp)
            elif fam == "ride":
                metric = mps_to_kmh(sp)
            else:
                metric = None
            if metric is not None:
                hist[_bucket(metric, edges)] = hist.get(_bucket(metric, edges), 0) + dt

    hist_rows = [
        {"activity_id": activity_id, "pace_family": fam, "bucket_idx": idx,
         "bucket_label": _bucket_label(idx, edges, unit, fam), "seconds": secs}
        for idx, secs in sorted(hist.items())
    ]
    return pd.DataFrame(sample_rows), pd.DataFrame(hist_rows)


def _insert_df(con, table: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    use = [c for c in cols if c in df.columns]
    con.register("_df", df[use])
    con.execute(f"INSERT INTO {table} ({', '.join(use)}) SELECT {', '.join(use)} FROM _df")
    con.unregister("_df")


def build(source: str = "fixtures", con=None) -> dict[str, int]:
    """Build CORE tables from a cache. Returns row counts. Reusable for both the
    'fixtures' and real 'raw' sources."""
    cfg = load_config()
    cache = cache_dir(source)
    owns = con is None
    con = con or schema.connect()
    try:
        schema.reset_core(con)
        schema.ensure_marts(con)

        activities, all_samples, all_hist = [], [], []
        stream_ids: set[int] = set()
        for p in _iter_activity_files(cache):
            raw = _read_json(p)
            row = _build_activity_row(raw, cfg)
            activities.append(row)

            sp = cache / STREAMS_SUBDIR / f"{row['id']}.json"
            if sp.exists():
                fam = row["pace_family"]
                edges, unit = _pace_edges(fam, cfg)
                s_df, h_df = _build_streams(_read_json(sp), fam, edges, unit, row["id"])
                if not s_df.empty:
                    row["has_streams"] = True
                    stream_ids.add(row["id"])
                    all_samples.append(s_df)
                    all_hist.append(h_df)

        _assign_race_events(activities, cfg)
        if activities:
            _insert_df(con, "activities", pd.DataFrame(activities))
        if all_samples:
            _insert_df(con, "samples", pd.concat(all_samples, ignore_index=True))
        if all_hist:
            _insert_df(con, "pace_histograms", pd.concat(all_hist, ignore_index=True))

        # athlete / gear (optional)
        ath = cache / ATHLETE_FILE
        if ath.exists():
            a = _read_json(ath)
            con.execute(
                "INSERT INTO athlete VALUES (?,?,?,?,?,?)",
                [a.get("id"), a.get("first_name"), a.get("last_name"),
                 a.get("measurement_preference"), a.get("weight"), json.dumps(a)],
            )
        gear = cache / GEAR_FILE
        if gear.exists():
            for g in _read_json(gear):
                con.execute(
                    "INSERT INTO gear VALUES (?,?,?,?)",
                    [str(g.get("id")), g.get("name"),
                     g.get("type", "shoe"), json.dumps(g)],
                )

        counts = {
            "activities": con.execute("SELECT count(*) FROM activities").fetchone()[0],
            "samples": con.execute("SELECT count(*) FROM samples").fetchone()[0],
            "pace_histograms":
                con.execute("SELECT count(*) FROM pace_histograms").fetchone()[0],
            "with_streams": len(stream_ids),
        }
        return counts
    finally:
        if owns:
            con.close()
