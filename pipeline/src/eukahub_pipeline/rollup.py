"""Roll leaf-level species features up every lineage into per-clade rollups.

The taxonomy comes from the taxdump (rank + materialized ltree ``path``), so a
species' lineage is just its ``path`` split on dots — no ETE3. Polars does the
fan-out: each species is exploded into its ancestors, then grouped by ancestor
and summed. This is the ~30-45M-row columnar group-by the redesign is built
around (DECISIONS.md: Polars for this step; Pandas ruled out).

Leaf features come from Euka-Survey's ``taxid_features`` table — a Phase 1
bridge; later phases repopulate it from fresh NCBI/Annotrieve/ENA fetches.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import polars as pl
from eukahub_core.metrics import COVERAGE_KEYS, METRIC_KEYS, TOTAL_KEYS

log = logging.getLogger("eukahub.rollup")


def load_leaf_features(sqlite_path: str | Path) -> pl.DataFrame:
    """Read ``taxid_features`` (one row per featured leaf taxid) into Polars."""
    con = sqlite3.connect(str(sqlite_path))
    try:
        rows = con.execute(
            "SELECT taxid, short_read_count, long_read_count, "
            "assembly_count, annotation_count FROM taxid_features"
        ).fetchall()
    finally:
        con.close()
    return pl.DataFrame(
        rows,
        schema={
            "taxid": pl.Int64,
            "short": pl.Int64,
            "long": pl.Int64,
            "ass": pl.Int64,
            "ann": pl.Int64,
        },
        orient="row",
    )


def _collect(lf: pl.LazyFrame) -> pl.DataFrame:
    """Collect, preferring the streaming engine (bounds memory on the ~50M-row
    exploded intermediate), with fallbacks across Polars versions."""
    try:
        return lf.collect(engine="streaming")
    except TypeError:
        try:
            return lf.collect(streaming=True)
        except TypeError:
            return lf.collect()


def rollup_from_frames(taxon: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """Roll species features up into per-clade rollups.

    ``taxon`` needs columns (taxid, rank, path); ``features`` needs
    (taxid, short, long, ass, ann). Returns one row per ancestor clade with
    columns (taxid, n_rows, c_*, s_*) in METRICS order. A species is included
    in its own lineage (``path`` ends with its taxid), matching Euka-Survey.
    """
    species = (
        features.join(taxon.select("taxid", "rank", "path"), on="taxid", how="inner")
        .filter(pl.col("rank") == "species")
        .with_columns(
            has_ass=(pl.col("ass") > 0).cast(pl.Int64),
            has_ann=(pl.col("ann") > 0).cast(pl.Int64),
            has_rna=((pl.col("short") + pl.col("long")) > 0).cast(pl.Int64),
            has_lng=(pl.col("long") > 0).cast(pl.Int64),
            s_ass=pl.col("ass"),
            s_ann=pl.col("ann"),
            s_rna=pl.col("short") + pl.col("long"),
            s_lng=pl.col("long"),
        )
    )

    carried = [f"has_{k}" for k in METRIC_KEYS] + [f"s_{k}" for k in METRIC_KEYS]
    aggs = [pl.len().alias("n_rows")]
    aggs += [pl.col(f"has_{k}").sum().alias(f"c_{k}") for k in METRIC_KEYS]
    aggs += [pl.col(f"s_{k}").sum().alias(f"s_{k}") for k in METRIC_KEYS]

    clade = (
        species.lazy()
        .select(pl.col("path").str.split(".").alias("anc"), *carried)
        .explode("anc")
        .with_columns(pl.col("anc").cast(pl.Int64).alias("taxid"))
        .group_by("taxid")
        .agg(aggs)
        .select("taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS)
    )
    return _collect(clade)


def rollup_clades(taxon: pl.DataFrame, leaf_features_sqlite: str | Path) -> pl.DataFrame:
    """Convenience wrapper: load leaf features from SQLite, then roll up."""
    features = load_leaf_features(leaf_features_sqlite)
    log.info("Loaded %d leaf feature rows", features.height)
    clade = rollup_from_frames(taxon, features)
    log.info("Rolled up into %d clade rows", clade.height)
    return clade
