"""Generate a deterministic SYNTHETIC Strava cache under data/fixtures/.

This is NOT real data — it mimics the shape the real harvester writes so the
transform/metrics/dashboard can be built and e2e-tested without the Strava MCP.
~20 months of multi-sport training with three triathlon races and rising
buildup volume before each, plus a gradual easy-pace improvement over time so
the "pace distribution over time" views show a real signal.

Run: `python scripts/make_fixtures.py`  (or `make fixtures`).
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "data" / "fixtures"
ACT = FX / "activities"
STR = FX / "streams"

RNG = random.Random(7)

START = date.today() - timedelta(days=620)        # ~20 months of history
END = date.today() - timedelta(days=2)

# Triathlon races (relative day offsets from START). Each becomes 3 activities.
RACES = [
    (240, "Gravenhurst Olympic Triathlon"),
    (430, "Ironman 70.3 Victoria"),
    (600, "T100 Vancouver Sprint Triathlon"),
]

GEAR = [
    {"id": "18532572", "name": "Daily Trainer", "type": "shoe"},
    {"id": "23558332", "name": "Race Flats", "type": "shoe"},
    {"id": "20574828", "name": "Trail Shoes", "type": "shoe"},
]


def _next_id(counter=[14000000000]):
    counter[0] += RNG.randint(1000, 9000)
    return counter[0]


def _improve(day_offset: float) -> float:
    """Fitness factor 0..1 rising over the 20 months -> faster easy pace."""
    return min(1.0, day_offset / 620.0)


def _buildup_boost(d: date) -> float:
    """Extra volume/intensity in the 16 weeks before each race."""
    boost = 0.0
    for off, _ in RACES:
        rday = START + timedelta(days=off)
        delta = (rday - d).days
        if 0 <= delta <= 112:
            boost = max(boost, 1.0 - delta / 112.0)
    return boost


def _make_streams(duration_s: int, target_mps: float, jitter: float,
                  hr_base: float, climb: float) -> dict:
    step = 15
    t, dist, vel, hr, alt, cad, mov = [], [], [], [], [], [], []
    cum = 0.0
    a = 0.0
    for sec in range(0, duration_s + 1, step):
        v = max(0.2, RNG.gauss(target_mps, jitter))
        # occasional walk/rest breaks
        moving = True
        if RNG.random() < 0.02:
            v, moving = 0.1, False
        cum += v * step
        a += RNG.gauss(climb * step, 0.3)
        t.append(sec)
        dist.append(round(cum, 1))
        vel.append(round(v, 3))
        hr.append(round(RNG.gauss(hr_base, 6), 0))
        alt.append(round(a, 1))
        cad.append(round(RNG.gauss(82, 4), 1))
        mov.append(moving)
    return {"time": t, "distance": dist, "velocity_smooth": vel,
            "heartrate": hr, "altitude": alt, "cadence": cad, "moving": mov}


def _summary_from_streams(s: dict) -> dict:
    vel = s["velocity_smooth"]
    dist = s["distance"][-1] if s["distance"] else 0
    dur = s["time"][-1] if s["time"] else 0
    moving = [v for v, m in zip(vel, s["moving"]) if m]
    avg = sum(moving) / len(moving) if moving else 0
    return {
        "distance": round(dist, 1),
        "moving_time": dur,
        "elapsed_time": dur + RNG.randint(0, 200),
        "elevation_gain": round(max(s["altitude"]) - min(s["altitude"]), 0)
        if s["altitude"] else 0,
        "avg_speed": round(avg, 4),
        "max_speed": round(max(vel), 2),
        "relative_effort": RNG.randint(5, 120),
        "total_calories": round(dist / 1000 * RNG.uniform(55, 75)),
        "avg_cadence": round(sum(s["cadence"]) / len(s["cadence"]), 2),
        "average_heartrate": round(sum(s["heartrate"]) / len(s["heartrate"]), 0),
        "max_heartrate": max(s["heartrate"]),
    }


def write_activity(d: date, hour: int, sport: str, name: str, target_mps: float,
                   jitter: float, duration_s: int, hr_base: float, climb: float,
                   gear_id=None, workout_type=None, streams=True):
    aid = _next_id()
    start_local = datetime(d.year, d.month, d.day, hour,
                           RNG.randint(0, 59), RNG.randint(0, 59))
    if streams:
        s = _make_streams(duration_s, target_mps, jitter, hr_base, climb)
        summ = _summary_from_streams(s)
        (STR / f"{aid}.json").write_text(
            json.dumps({"activity_id": aid, "streams": s}))
    else:
        dist = target_mps * duration_s
        summ = {"distance": round(dist, 1), "moving_time": duration_s,
                "elapsed_time": duration_s, "elevation_gain": 0,
                "avg_speed": target_mps, "max_speed": target_mps * 1.4,
                "relative_effort": RNG.randint(2, 20),
                "total_calories": RNG.randint(80, 300), "avg_cadence": 0}
    act = {"id": aid, "name": name, "sport_type": sport,
           "start_local": start_local.isoformat(timespec="seconds"),
           "summary": summ}
    if gear_id:
        act["gear_id"] = gear_id
    if workout_type is not None:
        act["workout_type"] = workout_type
    (ACT / f"{aid}.json").write_text(json.dumps(act))


def build_week(d: date):
    off = (d - START).days
    fit = _improve(off)
    boost = _buildup_boost(d)
    # easy run pace m/s improves from ~2.5 (6:40/km) to ~3.0 (5:33/km)
    easy = 2.5 + 0.45 * fit + 0.15 * boost
    shoe = RNG.choice(GEAR)["id"]

    # Easy run (Mon)
    write_activity(d, 7, "Run", "Morning Run", easy, 0.25,
                   int((35 + 15 * boost) * 60), 140, 0.02, shoe)
    # Quality run (Wed) — faster, more spread
    if RNG.random() < 0.85:
        write_activity(d + timedelta(days=2), 17, "Run",
                       "Morning Run - WU + intervals + CD", easy + 0.6, 0.55,
                       int((45 + 10 * boost) * 60), 165, 0.03, shoe, workout_type=3)
    # Long run (Sat) — grows with buildup
    write_activity(d + timedelta(days=5), 8, "Run", "Long Run",
                   easy - 0.1, 0.2, int((70 + 60 * boost) * 60), 150, 0.05, shoe)
    # Rides
    write_activity(d + timedelta(days=1), 12, "Ride", "Afternoon Ride",
                   8.0 + fit, 1.2, int((60 + 30 * boost) * 60), 135, 0.08)
    if RNG.random() < 0.7:
        write_activity(d + timedelta(days=3), 18, "VirtualRide",
                       "Zwift - Watopia", 9.0 + fit, 0.8,
                       int(60 * 60), 145, 0.0)
    # Swims
    write_activity(d + timedelta(days=1), 6, "Swim", "Morning Swim",
                   0.72 + 0.08 * fit, 0.12, int((30 + 10 * boost) * 60), 130, 0.0)
    if RNG.random() < 0.5:
        write_activity(d + timedelta(days=4), 12, "Swim", "Lunch Swim",
                       0.70 + 0.08 * fit, 0.1, int(35 * 60), 128, 0.0)
    # Non-stream activities
    if RNG.random() < 0.4:
        write_activity(d + timedelta(days=6), 11, "Walk", "Morning Walk",
                       1.4, 0.3, int(30 * 60), 95, 0.02, streams=False)
    if RNG.random() < 0.3:
        write_activity(d + timedelta(days=0), 12, "WeightTraining",
                       "Lunch Weight Training", 0.0, 0.0, int(40 * 60), 100, 0.0,
                       streams=False)


def write_race(off: int, name: str):
    d = START + timedelta(days=off)
    fit = _improve(off)
    # Swim / Bike / Run legs, race effort + workout_type=1 on the run.
    write_activity(d, 8, "Swim", f"{name} - Swim", 0.78 + 0.1 * fit, 0.08,
                   int(35 * 60), 150, 0.0)
    write_activity(d, 9, "Ride", f"{name} - Ride", 9.5 + fit, 0.9,
                   int(80 * 60), 155, 0.06)
    write_activity(d, 10, "Run", f"{name} - Run", 3.4 + 0.3 * fit, 0.3,
                   int(50 * 60), 172, 0.03, GEAR[1]["id"], workout_type=1)


def main():
    for p in (ACT, STR):
        p.mkdir(parents=True, exist_ok=True)
        for f in p.glob("*.json"):
            f.unlink()

    d = START
    while d <= END:
        build_week(d)
        d += timedelta(days=7)

    for off, name in RACES:
        write_race(off, name)

    (FX / "athlete.json").write_text(json.dumps({
        "id": 57826935, "first_name": "Francis", "last_name": "Silva",
        "measurement_preference": "Metric", "gender": "Man", "weight": 77.2,
        "location": {"city": "Vancouver/Toronto", "country": "Canada"},
    }))
    (FX / "gear.json").write_text(json.dumps(GEAR))

    n_act = len(list(ACT.glob("*.json")))
    n_str = len(list(STR.glob("*.json")))
    print(f"Wrote {n_act} activities and {n_str} stream files to {FX}")


if __name__ == "__main__":
    main()
