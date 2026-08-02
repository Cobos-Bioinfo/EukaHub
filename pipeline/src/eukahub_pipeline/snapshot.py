"""Resumable source snapshots.

Fetching all of Eukaryota is slow (datasets ~68k assemblies; ENA ~8M runs), so
each fetched source is cached to parquet and reused on the next build unless the
snapshot is missing or a refresh is forced. This is the resumable-snapshot half
of the resumable-snapshot + atomic-swap discipline (roadmap / DECISIONS.md): the
DB is still rebuilt and swapped wholesale, but re-fetching every source on every
run is avoided.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import polars as pl

log = logging.getLogger("eukahub.snapshot")


def cached_frame(
    name: str,
    fetch_fn: Callable[[], Iterable[Mapping[str, Any]]],
    schema: Mapping[str, Any],
    snapshot_dir: str | Path,
    *,
    refresh: bool = False,
) -> pl.DataFrame:
    """Return ``name``'s rows as a DataFrame.

    Reuses ``<snapshot_dir>/<name>.parquet`` when it exists and ``refresh`` is
    False; otherwise calls ``fetch_fn`` (live fetch), writes the snapshot, and
    returns it. ``schema`` pins the column dtypes so an all-null column never
    collapses to Null type across runs.
    """
    path = Path(snapshot_dir) / f"{name}.parquet"
    if path.exists() and not refresh:
        df = pl.read_parquet(path)
        log.info("snapshot %-11s reused  %8d rows  (%s)", name, df.height, path)
        return df

    df = pl.DataFrame(list(fetch_fn()), schema=dict(schema))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    log.info("snapshot %-11s fetched %8d rows -> %s", name, df.height, path)
    return df
