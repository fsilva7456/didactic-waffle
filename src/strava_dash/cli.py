"""Command-line entry point: `python -m strava_dash.cli ...` / `strava-dash ...`."""
from __future__ import annotations

import argparse
import sys


def _cmd_build(args) -> int:
    from . import transform
    counts = transform.build(source=args.source)
    print(f"Built CORE tables from '{args.source}':")
    for k, v in counts.items():
        print(f"  {k:16s} {v}")
    # Always (re)build marts after a core build so the DB is dashboard-ready.
    from . import metrics
    results = metrics.build_all()
    built = sum(1 for v in results.values() if v == "ok")
    print(f"Built {built}/{len(results)} metric modules.")
    for name, status in results.items():
        if status != "ok":
            print(f"  ! {name}: {status}", file=sys.stderr)
    return 0


def _cmd_marts(args) -> int:
    from . import metrics
    results = metrics.build_all()
    for name, status in results.items():
        print(f"  {name}: {status}")
    return 0


def _cmd_ingest(args) -> int:
    try:
        from . import ingest
    except ImportError:
        print("Ingest module not available yet (built as a separate work unit).",
              file=sys.stderr)
        return 1
    return ingest.run_cli(args)


def _cmd_info(args) -> int:
    from . import schema
    con = schema.connect(read_only=True)
    try:
        for tbl in list(schema.CORE_DDL) + list(schema.MART_DDL):
            try:
                n = con.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
            except Exception:
                n = "—"
            print(f"  {tbl:24s} {n}")
    finally:
        con.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="strava-dash")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Build CORE tables + marts from a cache")
    b.add_argument("--source", choices=["fixtures", "raw"], default="fixtures")
    b.set_defaults(func=_cmd_build)

    m = sub.add_parser("marts", help="Rebuild analytics marts only")
    m.set_defaults(func=_cmd_marts)

    ing = sub.add_parser("ingest", help="Harvest raw data from Strava (MCP)")
    ing.add_argument("--limit", type=int, default=None)
    ing.set_defaults(func=_cmd_ingest)

    i = sub.add_parser("info", help="Show table row counts")
    i.set_defaults(func=_cmd_info)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
