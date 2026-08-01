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


def _own_feature_cols() -> list[pl.Expr]:
    """Per-taxon has-flags (``has_<key>``) and summed totals (``s_<key>``) from
    the raw leaf counts — the directly-attached features of one taxid."""
    return [
        (pl.col("ass") > 0).cast(pl.Int64).alias("has_ass"),
        (pl.col("ann") > 0).cast(pl.Int64).alias("has_ann"),
        ((pl.col("short") + pl.col("long")) > 0).cast(pl.Int64).alias("has_rna"),
        (pl.col("long") > 0).cast(pl.Int64).alias("has_lng"),
        pl.col("ass").alias("s_ass"),
        pl.col("ann").alias("s_ann"),
        (pl.col("short") + pl.col("long")).alias("s_rna"),
        pl.col("long").alias("s_lng"),
    ]


def _species_rollup(taxon: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """Sum species features up every lineage into one row per ancestor clade.

    A species is included in its own lineage (``path`` ends with its taxid),
    matching Euka-Survey. ``n_rows`` counts the species in each clade's subtree.
    """
    species = (
        features.join(taxon.select("taxid", "rank", "path"), on="taxid", how="inner")
        .filter(pl.col("rank") == "species")
        .with_columns(_own_feature_cols())
    )

    carried = [f"has_{k}" for k in METRIC_KEYS] + [f"s_{k}" for k in METRIC_KEYS]
    aggs = [pl.len().cast(pl.Int64).alias("n_rows")]
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


def _infraspecific_rows(taxon: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """One rollup row per *below-species* taxon that carries directly-attached
    features (subspecies, strains, varietas, forma, isolates, ...).

    These are the resources NCBI/Annotrieve/ENA registered on a taxid finer than
    species. They are **not** rolled into any ancestor (the species-only rollup
    above is untouched), so a subspecies' data is navigable when focused on it
    but never inflates its parent species or any higher clade. Each row is the
    taxon's own counts, with ``n_rows = 1`` (the taxon itself as a single unit),
    so it renders like a leaf. A taxon is "below species" iff a proper ancestor
    in its ``path`` has rank ``species``; detection runs only over the small set
    of featured non-species taxa, so it is cheap.
    """
    empty = pl.DataFrame(
        schema={c: pl.Int64 for c in ("taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS)}
    )
    featured = (
        features.join(taxon.select("taxid", "rank", "path"), on="taxid", how="inner")
        .filter(pl.col("rank") != "species")
    )
    if featured.height == 0:
        return empty

    species_ids = taxon.filter(pl.col("rank") == "species").select(
        pl.col("taxid").alias("anc")
    )
    # A featured taxon is below-species iff one of its proper ancestors (path
    # labels other than itself) is a species.
    below_ids = (
        featured.select("taxid", pl.col("path").str.split(".").alias("anc"))
        .explode("anc")
        .with_columns(pl.col("anc").cast(pl.Int64))
        .filter(pl.col("anc") != pl.col("taxid"))
        .join(species_ids, on="anc", how="inner")
        .select("taxid")
        .unique()
    )
    if below_ids.height == 0:
        return empty

    rows = (
        featured.join(below_ids, on="taxid", how="inner")
        .with_columns(_own_feature_cols())
        .with_columns(pl.lit(1, dtype=pl.Int64).alias("n_rows"))
        .rename({f"has_{k}": f"c_{k}" for k in METRIC_KEYS})
        .select("taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS)
    )
    return rows


def rollup_from_frames(taxon: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """Roll leaf features into per-clade rollups.

    ``taxon`` needs columns (taxid, rank, path); ``features`` needs
    (taxid, short, long, ass, ann). Returns one row per taxon with columns
    (taxid, n_rows, c_*, s_*) in METRICS order, combining:

    - the **species rollup** — one row per ancestor clade, features summed up
      every species' lineage (``n_rows`` = species in the subtree); and
    - **below-species rows** — one row per featured infraspecific taxon
      (subspecies/strain/...), holding only its own directly-attached features
      with ``n_rows = 1``, never rolled into any ancestor.

    The two row-sets have disjoint taxids (an infraspecific taxon is never an
    ancestor of a species), so a plain vertical concat is exact.
    """
    clade = _species_rollup(taxon, features)
    infra = _infraspecific_rows(taxon, features)
    if infra.height == 0:
        return clade
    return pl.concat([clade, infra], how="vertical")


def rollup_clades(taxon: pl.DataFrame, leaf_features_sqlite: str | Path) -> pl.DataFrame:
    """Convenience wrapper: load leaf features from SQLite, then roll up."""
    features = load_leaf_features(leaf_features_sqlite)
    log.info("Loaded %d leaf feature rows", features.height)
    clade = rollup_from_frames(taxon, features)
    log.info("Rolled up into %d clade rows", clade.height)
    return clade
