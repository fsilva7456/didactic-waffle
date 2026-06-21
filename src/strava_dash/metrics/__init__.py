"""Metrics layer — each metric is a self-contained module that builds one or
more MART tables from the CORE tables.

CONTRACT for a metric module (so parallel work units never touch shared files):

    # src/strava_dash/metrics/<your_metric>.py
    MART_TABLES = ["mart_xxx"]          # the marts this module owns

    def build(con) -> None:
        '''Populate MART_TABLES from CORE tables. Idempotent: clear then fill.
        Tables already exist (schema.ensure_marts). Use DELETE + INSERT or
        CREATE OR REPLACE TABLE, keeping the columns declared in schema.MART_DDL.
        '''
        ...

`build_all` discovers every such module automatically — drop a new file in this
package and it is picked up with no central registration, so units stay
independently mergeable.
"""
from __future__ import annotations

import importlib
import pkgutil

from .. import schema


def discover() -> list:
    """Import and return all metric modules exposing a `build` callable."""
    mods = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "build") and callable(mod.build):
            mods.append(mod)
    return mods


def build_all(con=None) -> dict[str, str]:
    """Run every metric's build(). Returns {module: 'ok'|error}. Marts that have
    no module yet simply stay empty (created by ensure_marts)."""
    owns = con is None
    con = con or schema.connect()
    results: dict[str, str] = {}
    try:
        schema.ensure_core(con)
        schema.ensure_marts(con)
        for mod in discover():
            try:
                mod.build(con)
                results[mod.__name__] = "ok"
            except Exception as exc:  # keep building other marts
                results[mod.__name__] = f"error: {exc}"
        return results
    finally:
        if owns:
            con.close()
