"""Resumable ingestion harness for the raw Strava cache.

The real data source is the Strava MCP, which is only available inside an
interactive Claude session (not in background/worktree agents or CI). So this
module is structured around a small ``Fetcher`` interface that can be backed by
either:

* ``MCPFetcher`` — driven by Claude via the Strava MCP tools (the real run), or
* ``ReplayFetcher`` — reads an existing on-disk cache (e.g. ``data/fixtures/``)
  to simulate Strava for tests and dry runs.

``harvest`` pages activities across a window, writes each activity summary and
its streams into the canonical cache layout that ``transform.py`` reads, and
records progress in a JSON ``Manifest`` after every item so an interrupted run
resumes without re-fetching. Everything is idempotent: already-cached items are
skipped.

Canonical cache layout written here (identical to what the fixtures produce):

    <cache>/activities/<id>.json
    <cache>/streams/<id>.json
    <cache>/athlete.json
    <cache>/gear.json
    data/manifest.json              # sync state (Manifest)
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from .paths import (
    ACTIVITIES_SUBDIR,
    ATHLETE_FILE,
    DATA_DIR,
    GEAR_FILE,
    MANIFEST_FILE,
    RAW_DIR,
    STREAMS_SUBDIR,
)


# --- manifest ----------------------------------------------------------------


@dataclass
class Manifest:
    """Persisted sync state. Tracks which activities have been fetched, which
    have cached streams, how far back the harvest has reached, when it last ran,
    and any per-activity errors. Resumable: ``harvest`` consults it to skip work
    already done on a previous (possibly interrupted) run."""

    fetched_ids: list[int] = field(default_factory=list)
    streamed_ids: list[int] = field(default_factory=list)
    # Informational only: the last page cursor reached, and the oldest activity
    # day fetched so far. harvest() deliberately does NOT resume from end_cursor
    # (it re-pages from the window start, skipping cached ids), so these are
    # recorded for observability, not used to drive paging.
    end_cursor: Optional[str] = None
    oldest_date: Optional[str] = None
    last_synced: Optional[str] = None
    errors: dict[str, str] = field(default_factory=dict)

    # --- persistence ---

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        """Load a manifest from ``path``; return a fresh empty one if absent or
        unreadable (a corrupt manifest should never block a re-harvest)."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # noqa: SIM118
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write so an interrupted save can't truncate the manifest.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(path)

    # --- mutation helpers (keep lists set-like + sorted, JSON-friendly) ---

    def mark_fetched(self, activity_id: int, start_local: str | None = None) -> None:
        aid = int(activity_id)
        if aid not in self.fetched_ids:
            self.fetched_ids.append(aid)
            self.fetched_ids.sort()
        if start_local:
            day = start_local[:10]
            if self.oldest_date is None or day < self.oldest_date:
                self.oldest_date = day
        # A successful fetch clears any prior error for this id.
        self.errors.pop(str(aid), None)

    def mark_streamed(self, activity_id: int) -> None:
        aid = int(activity_id)
        if aid not in self.streamed_ids:
            self.streamed_ids.append(aid)
            self.streamed_ids.sort()
        self.errors.pop(str(aid), None)

    def record_error(self, activity_id: int, message: str) -> None:
        self.errors[str(int(activity_id))] = message

    def has_fetched(self, activity_id: int) -> bool:
        return int(activity_id) in self.fetched_ids

    def has_streamed(self, activity_id: int) -> bool:
        return int(activity_id) in self.streamed_ids

    def touch(self) -> None:
        self.last_synced = datetime.now(timezone.utc).isoformat()


# --- fetcher interface -------------------------------------------------------


class Fetcher(Protocol):
    """Source of Strava data. Implementations need only return plain JSON-able
    dicts/lists in the canonical shapes."""

    def list_activities(
        self,
        start: str | None = None,
        end: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        """Return one page:
        ``{"activities": [<summary>...], "has_next_page": bool,
           "end_cursor": str | None}``."""
        ...

    def get_streams(self, activity_id: int) -> dict:
        """Return ``{"activity_id": id, "streams": {<name>: [...]}}``."""
        ...

    def get_athlete(self) -> dict:
        ...

    def get_gear(self) -> list:
        ...


# --- cache writing -----------------------------------------------------------


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class _Paths:
    """Resolved output locations for a harvest. Defaults to the real raw cache
    but tests can pass an explicit cache/manifest pair to write to a tmp dir."""

    cache: Path
    manifest: Path

    @property
    def activities(self) -> Path:
        return self.cache / ACTIVITIES_SUBDIR

    @property
    def streams(self) -> Path:
        return self.cache / STREAMS_SUBDIR

    @property
    def athlete(self) -> Path:
        return self.cache / ATHLETE_FILE

    @property
    def gear(self) -> Path:
        return self.cache / GEAR_FILE


def _resolve_paths(cache_dir: Path | str | None,
                   manifest_path: Path | str | None) -> _Paths:
    cache = Path(cache_dir) if cache_dir is not None else RAW_DIR
    if manifest_path is not None:
        manifest = Path(manifest_path)
    elif cache_dir is not None:
        # An explicit cache keeps its manifest alongside it (test-friendly).
        manifest = cache / MANIFEST_FILE
    else:
        manifest = DATA_DIR / MANIFEST_FILE
    return _Paths(cache=cache, manifest=manifest)


# --- the harvester -----------------------------------------------------------


def harvest(
    fetcher: Fetcher,
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
    sleep: Callable[[], None] | None = None,
    cache_dir: Path | str | None = None,
    manifest_path: Path | str | None = None,
    resume: bool = True,
) -> dict:
    """Harvest activities + streams into the canonical cache and update the
    manifest after every item (so an interrupted run resumes cleanly).

    Parameters
    ----------
    fetcher:        a :class:`Fetcher` (real MCP-backed or a replay/fake).
    start, end:     ISO date bounds for the activity window (passed through to
                    ``list_activities``; semantics are the fetcher's).
    limit:          stop after writing this many *newly fetched* activities.
    sleep:          optional hook invoked between network requests — the seam
                    for rate-limiting / backoff.
    cache_dir:      where to write the cache (defaults to ``data/raw``).
    manifest_path:  where to persist the manifest (defaults next to the cache,
                    or ``data/manifest.json`` for the real raw cache).
    resume:         load the existing manifest and skip already-cached items.

    Returns a small summary dict of what happened.
    """
    paths = _resolve_paths(cache_dir, manifest_path)
    manifest = Manifest.load(paths.manifest) if resume else Manifest()

    def _sleep() -> None:
        if sleep is not None:
            sleep()

    summary = {
        "activities_fetched": 0,
        "activities_skipped": 0,
        "streams_fetched": 0,
        "streams_skipped": 0,
        "pages": 0,
        "errors": 0,
    }

    # 1) Reference data (athlete + gear) — fetched once per run, cheap.
    try:
        _write_json(paths.athlete, fetcher.get_athlete())
        _sleep()
    except Exception as exc:  # pragma: no cover - defensive
        manifest.record_error(-1, f"athlete: {exc}")
        summary["errors"] += 1
    try:
        _write_json(paths.gear, fetcher.get_gear())
        _sleep()
    except Exception as exc:  # pragma: no cover - defensive
        manifest.record_error(-2, f"gear: {exc}")
        summary["errors"] += 1

    # 2) Page through activities, writing each summary as we go.
    #
    #    We always re-page from the START of the window (cursor=None) rather than
    #    resuming from the manifest's saved cursor: with --limit an interrupted
    #    run can stop partway through a page, so a saved cursor could skip
    #    not-yet-fetched activities. The manifest's has_fetched() check makes the
    #    re-page cheap and idempotent (already-cached items are skipped, never
    #    re-written). end_cursor is persisted as informational sync state.
    cursor = None
    reached_limit = False
    while not reached_limit:
        page = fetcher.list_activities(start=start, end=end, cursor=cursor)
        summary["pages"] += 1
        activities = page.get("activities") or []
        for act in activities:
            aid = int(act["id"])
            act_path = paths.activities / f"{aid}.json"
            if manifest.has_fetched(aid) and act_path.exists():
                summary["activities_skipped"] += 1
                continue
            if limit is not None and summary["activities_fetched"] >= limit:
                reached_limit = True
                break
            _write_json(act_path, act)
            manifest.mark_fetched(aid, act.get("start_local"))
            summary["activities_fetched"] += 1
            manifest.save(paths.manifest)  # resumable after each item

        cursor = page.get("end_cursor")
        manifest.end_cursor = cursor
        manifest.save(paths.manifest)
        if reached_limit or not page.get("has_next_page"):
            break
        _sleep()

    # 3) Fetch streams for every cached activity that lacks them. Streams are
    #    the expensive per-activity call, so this is the part that benefits most
    #    from being resumable + idempotent.
    for aid in list(manifest.fetched_ids):
        stream_path = paths.streams / f"{aid}.json"
        # The manifest is authoritative for "this stream request was handled":
        # an activity with no stream data (manual/weights entry) is marked
        # streamed but has no file, so we must not gate the skip on file
        # existence — that would re-request it on every run.
        if manifest.has_streamed(aid):
            summary["streams_skipped"] += 1
            continue
        try:
            _sleep()
            blob = fetcher.get_streams(aid)
        except Exception as exc:
            manifest.record_error(aid, f"streams: {exc}")
            manifest.save(paths.manifest)
            summary["errors"] += 1
            continue
        if blob is None:
            # No stream data for this activity (e.g. manual/weights entry).
            # Record it as handled so we don't re-request it every run.
            manifest.mark_streamed(aid)
            manifest.save(paths.manifest)
            continue
        _write_json(stream_path, blob)
        manifest.mark_streamed(aid)
        summary["streams_fetched"] += 1
        manifest.save(paths.manifest)  # resumable after each item

    manifest.touch()
    manifest.save(paths.manifest)
    summary["manifest"] = str(paths.manifest)
    return summary


# --- fetcher implementations -------------------------------------------------


class ReplayFetcher:
    """A :class:`Fetcher` that replays an existing on-disk cache (the fixtures,
    or a previously harvested ``data/raw``) to simulate Strava without a
    network. Used by the unit tests and for offline dry runs.

    It pages the cache's ``activities/<id>.json`` files in newest-first order
    using a simple opaque integer offset as the cursor.
    """

    def __init__(self, cache_dir: Path | str, page_size: int = 50) -> None:
        self.cache = Path(cache_dir)
        self.page_size = page_size

    def _all_activities(self) -> list[dict]:
        d = self.cache / ACTIVITIES_SUBDIR
        if not d.exists():
            return []
        acts = [_read_json(p) for p in d.glob("*.json")]
        # Newest first, matching Strava's list ordering. Fall back to id.
        acts.sort(key=lambda a: (a.get("start_local") or "", a.get("id", 0)),
                  reverse=True)
        return acts

    def list_activities(
        self,
        start: str | None = None,
        end: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        acts = self._all_activities()
        if start is not None:
            lo = str(start)[:10]
            acts = [a for a in acts
                    if a.get("start_local") and a["start_local"][:10] >= lo]
        if end is not None:
            hi = str(end)[:10]
            acts = [a for a in acts
                    if a.get("start_local") and a["start_local"][:10] <= hi]
        offset = int(cursor) if cursor else 0
        page = acts[offset:offset + self.page_size]
        next_offset = offset + len(page)
        has_next = next_offset < len(acts)
        return {
            "activities": page,
            "has_next_page": has_next,
            "end_cursor": str(next_offset) if has_next else None,
        }

    def get_streams(self, activity_id: int) -> dict | None:
        p = self.cache / STREAMS_SUBDIR / f"{int(activity_id)}.json"
        if not p.exists():
            return None
        return _read_json(p)

    def get_athlete(self) -> dict:
        p = self.cache / ATHLETE_FILE
        return _read_json(p) if p.exists() else {}

    def get_gear(self) -> list:
        p = self.cache / GEAR_FILE
        return _read_json(p) if p.exists() else []


class MCPFetcher:
    """The real :class:`Fetcher`, backed by the Strava MCP tools. It is meant to
    be driven by Claude *inside an interactive session* where the MCP server is
    attached; background/worktree agents and CI do not have it.

    The interactive recipe is: Claude calls the MCP tools and passes their
    results into ``harvest`` via this fetcher. The mapping is:

        list_activities   <- mcp tool ``list_activities``
        get_streams       <- mcp tool ``get_activity_streams``
        get_athlete       <- mcp tool ``get_athlete_profile``
        get_gear          <- mcp tool ``get_gear``

    Because those tools are not importable here, every method raises
    ``NotImplementedError``. To run the real harvest, implement these methods in
    the interactive session by forwarding to the MCP tool calls (or subclass and
    override), then call ``harvest(MCPFetcher(...))``.
    """

    _MSG = "run inside an interactive Claude session with the Strava MCP"

    def list_activities(
        self,
        start: str | None = None,
        end: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        raise NotImplementedError(self._MSG)

    def get_streams(self, activity_id: int) -> dict:
        raise NotImplementedError(self._MSG)

    def get_athlete(self) -> dict:
        raise NotImplementedError(self._MSG)

    def get_gear(self) -> list:
        raise NotImplementedError(self._MSG)


# --- CLI ---------------------------------------------------------------------

_GUIDANCE = """\
strava-dash ingest — harvest raw Strava data into data/raw/

The Strava MCP that supplies real data is bound to an INTERACTIVE Claude
session; it is not available to background/worktree agents or CI, so this
command cannot harvest live data on its own.

How the real harvest works (interactive session):
  1. Claude drives the Strava MCP tools (list_activities, get_activity_streams,
     get_athlete_profile, get_gear) to fetch your data.
  2. Those results are fed into strava_dash.ingest.harvest() through an
     MCPFetcher, which writes the canonical cache:
         data/raw/activities/<id>.json
         data/raw/streams/<id>.json
         data/raw/athlete.json, data/raw/gear.json
     and records progress in data/manifest.json so it is RESUMABLE — an
     interrupted run picks up exactly where it left off and never re-fetches a
     cached activity or stream.
  3. --limit N caps the number of newly fetched activities (handy for a quick
     first pull or to stay under Strava's rate limits: 200 req / 15 min).

Once data/raw/ is populated, build the database with:
     python -m strava_dash.cli build --source raw

Offline, the ReplayFetcher can replay an existing cache (e.g. data/fixtures/)
to exercise this exact pipeline without the network — see tests/test_ingest.py.
"""


def run_cli(args) -> int:
    """Entry point for ``python -m strava_dash.cli ingest``.

    Without a live MCP this prints clear guidance and exits 0 (it must not
    crash). ``--limit`` is accepted and surfaced in the guidance.
    """
    limit = getattr(args, "limit", None)
    print(_GUIDANCE)
    if limit is not None:
        print(f"(--limit set to {limit}; it will cap newly fetched activities "
              f"in an interactive harvest.)")
    print("\nNo Strava MCP available in this environment; nothing harvested.",
          file=sys.stderr)
    return 0
