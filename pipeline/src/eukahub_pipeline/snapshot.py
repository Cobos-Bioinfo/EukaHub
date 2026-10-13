"""Resumable source snapshots.

Fetching all of Eukaryota is slow (datasets ~68k assemblies; ENA ~8M runs), so
each fetched source is cached to parquet and reused on the next build unless the
snapshot is missing or a refresh is forced. This is the resumable-snapshot half
of the resumable-snapshot + atomic-swap discipline (docs/architecture.md): the
DB is still rebuilt and swapped wholesale, but re-fetching every source on every
run is avoided.
"""

from __future__ import annotations

import itertools
import logging
import shutil
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import polars as pl
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger("eukahub.snapshot")

# Rows held in memory at a time while a fetch is written to disk.
BATCH_ROWS = 20_000
# Attempts at a fetch that fails with one of the caller's ``retry_on`` errors, and
# the wait between them.
FETCH_ATTEMPTS = 4
FETCH_WAIT = wait_exponential(multiplier=30, min=30, max=300)


def cached_frame(
    name: str,
    fetch_fn: Callable[[], Iterable[Mapping[str, Any]]],
    schema: Mapping[str, Any],
    snapshot_dir: str | Path,
    *,
    refresh: bool = False,
    retry_on: tuple[type[BaseException], ...] = (),
) -> pl.DataFrame:
    """Return ``name``'s rows as a DataFrame.

    Reuses ``<snapshot_dir>/<name>.parquet`` when it exists and ``refresh`` is
    False; otherwise calls ``fetch_fn`` (live fetch), writes the snapshot, and
    returns it. ``schema`` pins the column dtypes so an all-null column never
    collapses to Null type across runs.

    A live fetch is written to part files ``BATCH_ROWS`` rows at a time, and the
    snapshot appears only once the fetch completes, so a failed fetch never
    leaves a partial snapshot to be reused. A fetch that fails with one of
    ``retry_on`` is started again from scratch, ``FETCH_ATTEMPTS`` times in all,
    for a source with no retries of its own.
    """
    path = Path(snapshot_dir) / f"{name}.parquet"
    if path.exists() and not refresh:
        df = pl.read_parquet(path)
        log.info("snapshot %-11s reused  %8d rows  (%s)", name, df.height, path)
        return df

    parts = path.with_suffix(".parts")
    for attempt in Retrying(
        retry=retry_if_exception_type(retry_on),
        stop=stop_after_attempt(FETCH_ATTEMPTS),
        wait=FETCH_WAIT,
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    ):
        with attempt:
            files = _fetch_parts(fetch_fn, schema, parts)
    partial = path.with_suffix(".partial")
    if files:
        pl.scan_parquet(files).sink_parquet(partial)
    else:
        pl.DataFrame(schema=dict(schema)).write_parquet(partial)
    partial.replace(path)
    shutil.rmtree(parts)

    df = pl.read_parquet(path)
    log.info("snapshot %-11s fetched %8d rows -> %s", name, df.height, path)
    return df


def _fetch_parts(
    fetch_fn: Callable[[], Iterable[Mapping[str, Any]]], schema: Mapping[str, Any], parts: Path
) -> list[Path]:
    """Run ``fetch_fn`` into fresh part files under ``parts``, ``BATCH_ROWS`` rows each."""
    shutil.rmtree(parts, ignore_errors=True)
    parts.mkdir(parents=True)
    files = []
    for i, batch in enumerate(itertools.batched(fetch_fn(), BATCH_ROWS)):
        files.append(parts / f"{i:06d}.parquet")
        pl.DataFrame(list(batch), schema=dict(schema)).write_parquet(files[-1])
    return files
