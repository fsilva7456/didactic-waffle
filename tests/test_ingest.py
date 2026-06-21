"""Unit tests for the ingestion harness, driven by the ReplayFetcher over the
synthetic fixtures. No Strava MCP / network needed; everything writes to tmp
dirs so the real data/raw/ cache is never touched."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from strava_dash import ingest
from strava_dash.ingest import Manifest, ReplayFetcher, harvest
from strava_dash.paths import (
    ACTIVITIES_SUBDIR,
    ATHLETE_FILE,
    FIXTURES_DIR,
    GEAR_FILE,
    STREAMS_SUBDIR,
)


@pytest.fixture(scope="module")
def fixtures_cache() -> Path:
    """Ensure the synthetic fixtures exist; return the fixtures cache dir."""
    if not (FIXTURES_DIR / ACTIVITIES_SUBDIR).exists():
        import scripts.make_fixtures as mk  # type: ignore

        mk.main()
    return FIXTURES_DIR


class CountingFetcher:
    """Wraps a Fetcher and counts calls per method, so tests can assert that a
    second harvest re-fetches nothing."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: dict[str, int] = {
            "list_activities": 0,
            "get_streams": 0,
            "get_athlete": 0,
            "get_gear": 0,
        }
        self.calls_seen_streams: list[int] = []

    def list_activities(self, start=None, end=None, cursor=None):
        self.calls["list_activities"] += 1
        return self.inner.list_activities(start=start, end=end, cursor=cursor)

    def get_streams(self, activity_id):
        self.calls["get_streams"] += 1
        self.calls_seen_streams.append(int(activity_id))
        return self.inner.get_streams(activity_id)

    def get_athlete(self):
        self.calls["get_athlete"] += 1
        return self.inner.get_athlete()

    def get_gear(self):
        self.calls["get_gear"] += 1
        return self.inner.get_gear()


def _cache_paths(tmp_path: Path):
    return tmp_path / "raw", tmp_path / "manifest.json"


def test_harvest_writes_activities_streams_and_manifest(fixtures_cache, tmp_path):
    cache, manifest_path = _cache_paths(tmp_path)
    fetcher = ReplayFetcher(fixtures_cache, page_size=40)

    summary = harvest(fetcher, cache_dir=cache, manifest_path=manifest_path)

    act_files = list((cache / ACTIVITIES_SUBDIR).glob("*.json"))
    str_files = list((cache / STREAMS_SUBDIR).glob("*.json"))
    n_src_act = len(list((fixtures_cache / ACTIVITIES_SUBDIR).glob("*.json")))
    n_src_str = len(list((fixtures_cache / STREAMS_SUBDIR).glob("*.json")))

    assert len(act_files) == n_src_act
    assert len(str_files) == n_src_str
    assert summary["activities_fetched"] == n_src_act
    assert summary["streams_fetched"] == n_src_str

    # Reference data written.
    assert (cache / ATHLETE_FILE).exists()
    assert (cache / GEAR_FILE).exists()

    # An activity file round-trips to the canonical shape.
    sample = json.loads(act_files[0].read_text())
    assert "id" in sample and "summary" in sample

    # Manifest written and consistent.
    assert manifest_path.exists()
    m = Manifest.load(manifest_path)
    assert len(m.fetched_ids) == n_src_act
    assert len(m.streamed_ids) == n_src_act  # every id is resolved (some w/o data)
    assert m.last_synced is not None
    assert m.errors == {}


def test_second_harvest_is_idempotent(fixtures_cache, tmp_path):
    cache, manifest_path = _cache_paths(tmp_path)
    fetcher = CountingFetcher(ReplayFetcher(fixtures_cache, page_size=40))

    harvest(fetcher, cache_dir=cache, manifest_path=manifest_path)
    first_streams = fetcher.calls["get_streams"]
    assert first_streams > 0

    # Second run over the same cache/manifest must re-fetch no streams.
    fetcher.calls["get_streams"] = 0
    summary2 = harvest(fetcher, cache_dir=cache, manifest_path=manifest_path)

    assert fetcher.calls["get_streams"] == 0
    assert summary2["streams_fetched"] == 0
    assert summary2["activities_fetched"] == 0
    assert summary2["activities_skipped"] > 0


def test_interrupted_run_resumes(fixtures_cache, tmp_path):
    """A first capped run, then an uncapped run, together fetch everything once
    — simulating an interruption + resume without re-fetching."""
    cache, manifest_path = _cache_paths(tmp_path)
    fetcher = CountingFetcher(ReplayFetcher(fixtures_cache, page_size=40))

    harvest(fetcher, cache_dir=cache, manifest_path=manifest_path, limit=10)
    n_src_act = len(list((fixtures_cache / ACTIVITIES_SUBDIR).glob("*.json")))
    streamed_ids_after_first = set(Manifest.load(manifest_path).streamed_ids)

    fetcher.calls_seen_streams.clear()
    harvest(fetcher, cache_dir=cache, manifest_path=manifest_path)

    act_files = list((cache / ACTIVITIES_SUBDIR).glob("*.json"))
    str_files = list((cache / STREAMS_SUBDIR).glob("*.json"))
    n_src_str = len(list((fixtures_cache / STREAMS_SUBDIR).glob("*.json")))
    assert len(act_files) == n_src_act
    # All stream files are present, none fetched twice.
    assert len(str_files) == n_src_str

    # The second run must not re-request any stream already resolved by the
    # first (capped) run — resume skips them via the manifest.
    requested_again = set(fetcher.calls_seen_streams) & streamed_ids_after_first
    assert requested_again == set()

    m = Manifest.load(manifest_path)
    assert len(m.fetched_ids) == n_src_act
    assert len(m.streamed_ids) == n_src_act


def test_limit_is_respected(fixtures_cache, tmp_path):
    cache, manifest_path = _cache_paths(tmp_path)
    fetcher = ReplayFetcher(fixtures_cache, page_size=40)

    summary = harvest(fetcher, cache_dir=cache, manifest_path=manifest_path,
                      limit=5)

    act_files = list((cache / ACTIVITIES_SUBDIR).glob("*.json"))
    assert summary["activities_fetched"] == 5
    assert len(act_files) == 5


def test_replay_fetcher_date_window(fixtures_cache):
    """start/end bounds filter the activity window inclusively, tolerate a full
    ISO timestamp bound, and skip activities lacking start_local."""
    fetcher = ReplayFetcher(fixtures_cache, page_size=10_000)
    all_acts = fetcher.list_activities()["activities"]
    days = sorted({a["start_local"][:10] for a in all_acts})
    lo, hi = days[len(days) // 3], days[2 * len(days) // 3]

    windowed = fetcher.list_activities(start=lo, end=hi)["activities"]
    assert windowed, "expected some activities in the window"
    for a in windowed:
        assert lo <= a["start_local"][:10] <= hi
    # Boundary days are inclusive.
    got_days = {a["start_local"][:10] for a in windowed}
    assert lo in got_days and hi in got_days

    # A full ISO timestamp as the bound must behave like its date (boundary
    # day still included, not silently dropped by length mismatch).
    ts_windowed = fetcher.list_activities(start=f"{lo}T00:00:00",
                                          end=f"{hi}T23:59:59")["activities"]
    assert {a["id"] for a in ts_windowed} == {a["id"] for a in windowed}


def test_sleep_hook_is_called(fixtures_cache, tmp_path):
    cache, manifest_path = _cache_paths(tmp_path)
    fetcher = ReplayFetcher(fixtures_cache, page_size=40)
    calls = {"n": 0}

    def sleep():
        calls["n"] += 1

    harvest(fetcher, cache_dir=cache, manifest_path=manifest_path, limit=3,
            sleep=sleep)
    assert calls["n"] > 0


def test_manifest_load_missing_returns_empty(tmp_path):
    m = Manifest.load(tmp_path / "nope.json")
    assert m.fetched_ids == []
    assert m.streamed_ids == []
    assert m.last_synced is None


def test_manifest_roundtrip(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest()
    m.mark_fetched(123, "2025-01-02T07:00:00")
    m.mark_fetched(456, "2024-12-31T08:00:00")
    m.mark_streamed(123)
    m.record_error(789, "boom")
    m.touch()
    m.save(path)

    loaded = Manifest.load(path)
    assert loaded.has_fetched(123)
    assert loaded.has_streamed(123)
    assert not loaded.has_streamed(456)
    assert loaded.oldest_date == "2024-12-31"
    assert loaded.errors == {"789": "boom"}
    assert loaded.last_synced is not None


def test_corrupt_manifest_is_ignored(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not valid json")
    m = Manifest.load(path)
    assert m.fetched_ids == []


def test_mcp_fetcher_raises():
    f = ingest.MCPFetcher()
    for call in (lambda: f.list_activities(),
                 lambda: f.get_streams(1),
                 f.get_athlete,
                 f.get_gear):
        with pytest.raises(NotImplementedError):
            call()


def test_run_cli_prints_guidance_and_returns_zero(capsys):
    class Args:
        limit = 7

    rc = ingest.run_cli(Args())
    out = capsys.readouterr().out
    assert rc == 0
    assert "--limit" in out
    assert "7" in out


def test_run_cli_handles_missing_limit():
    class Args:
        pass

    assert ingest.run_cli(Args()) == 0
