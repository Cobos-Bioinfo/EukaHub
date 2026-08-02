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
from eukahub_core.metrics import (
    ASSEMBLY_LEVEL_TO_COLUMN,
    COMPOSITION_COLUMNS,
    COVERAGE_KEYS,
    METRIC_KEYS,
    TOTAL_KEYS,
)

log = logging.getLogger("eukahub.rollup")

# The per-taxid leaf inputs the fan-out consumes: raw read counts + assembly and
# annotation totals + the additive assembly-composition columns.
_LEAF_COUNT_COLUMNS: tuple[str, ...] = ("ass", "ann", "short", "long", *COMPOSITION_COLUMNS)


def assemble_leaf_features(
    assemblies: pl.DataFrame, annotations: pl.DataFrame, reads: pl.DataFrame
) -> pl.DataFrame:
    """Combine the three fetched sources into one per-taxid leaf-features frame.

    Produces columns ``(taxid, short, long, ass, ann, *COMPOSITION_COLUMNS)`` —
    the input the roll-up sums up every lineage. Assemblies contribute the total
    count, the per-``assembly_level`` split, and the reference-genome count;
    annotations contribute their count; reads their short/long run counts.
    Sources are joined on ``taxid`` (a full outer join, missing counts -> 0), so
    a taxon that appears in only one source still gets a complete row.
    """
    per_assembly = assemblies.group_by("taxid").agg(
        pl.len().cast(pl.Int64).alias("ass"),
        *[
            (pl.col("assembly_level") == level).sum().cast(pl.Int64).alias(col)
            for level, col in ASSEMBLY_LEVEL_TO_COLUMN.items()
        ],
        pl.col("refseq_category").is_not_null().sum().cast(pl.Int64).alias("n_reference"),
    )
    per_annotation = annotations.group_by("taxid").agg(pl.len().cast(pl.Int64).alias("ann"))
    per_reads = reads.select(
        "taxid", pl.col("short").cast(pl.Int64), pl.col("long").cast(pl.Int64)
    )

    leaf = (
        per_assembly.join(per_annotation, on="taxid", how="full", coalesce=True)
        .join(per_reads, on="taxid", how="full", coalesce=True)
        .with_columns([pl.col(c).fill_null(0).cast(pl.Int64) for c in _LEAF_COUNT_COLUMNS])
    )
    log.info("Assembled leaf features for %d taxa", leaf.height)
    return leaf


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


def _species_rollup(
    taxon: pl.DataFrame, features: pl.DataFrame, root_taxid: int | None = None
) -> pl.DataFrame:
    """Sum species features up every lineage into one row per ancestor clade.

    A species is included in its own lineage (``path`` ends with its taxid),
    matching Euka-Survey. ``n_rows`` counts the species in each clade's subtree.

    The universe of species is **the taxonomy**, not the feature rows: we start
    from every ``rank == 'species'`` node and LEFT-join the (sparse) feature data,
    zero-filling species with none. So ``n_rows`` counts *all* species in a clade
    (the coverage denominator and the "total species" figure), while c_*/s_* only
    accumulate the ones that actually carry data. (The fetched sources cover only
    a small fraction of the ~1.9M eukaryote species, so an inner join here would
    undercount ``n_rows`` badly.)

    ``root_taxid`` scopes the species universe to that root's subtree — the app
    is Eukaryota-only, and ``taxon`` holds the whole NCBI tree (all domains), so
    without it the rollup would also emit ~0.8M zero-data bacterial/viral clades.
    A species is in-subtree iff ``root_taxid`` is one of its ``path`` labels.
    """
    species_nodes = taxon.filter(pl.col("rank") == "species").select("taxid", "path")
    if root_taxid is not None:
        species_nodes = species_nodes.filter(
            pl.col("path").str.split(".").list.contains(str(root_taxid))
        )
    species = (
        species_nodes.join(features, on="taxid", how="left")
        .with_columns([pl.col(c).fill_null(0) for c in _LEAF_COUNT_COLUMNS])
        .with_columns(_own_feature_cols())
    )

    carried = (
        [f"has_{k}" for k in METRIC_KEYS]
        + [f"s_{k}" for k in METRIC_KEYS]
        + list(COMPOSITION_COLUMNS)
    )
    aggs = [pl.len().cast(pl.Int64).alias("n_rows")]
    aggs += [pl.col(f"has_{k}").sum().alias(f"c_{k}") for k in METRIC_KEYS]
    aggs += [pl.col(f"s_{k}").sum().alias(f"s_{k}") for k in METRIC_KEYS]
    aggs += [pl.col(c).sum().alias(c) for c in COMPOSITION_COLUMNS]

    clade = (
        species.lazy()
        .select(pl.col("path").str.split(".").alias("anc"), *carried)
        .explode("anc")
        .with_columns(pl.col("anc").cast(pl.Int64).alias("taxid"))
        .group_by("taxid")
        .agg(aggs)
        .select("taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS, *COMPOSITION_COLUMNS)
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
        schema={
            c: pl.Int64
            for c in ("taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS, *COMPOSITION_COLUMNS)
        }
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
        .select("taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS, *COMPOSITION_COLUMNS)
    )
    return rows


def _with_composition_defaults(features: pl.DataFrame) -> pl.DataFrame:
    """Ensure the additive composition columns exist (0 when a caller passes the
    minimal ``{taxid, short, long, ass, ann}`` frame — the SQLite bridge / unit
    tests). ``assemble_leaf_features`` already provides them."""
    missing = [c for c in COMPOSITION_COLUMNS if c not in features.columns]
    if missing:
        features = features.with_columns(
            [pl.lit(0, dtype=pl.Int64).alias(c) for c in missing]
        )
    return features


def rollup_from_frames(
    taxon: pl.DataFrame, features: pl.DataFrame, root_taxid: int | None = None
) -> pl.DataFrame:
    """Roll leaf features into per-clade rollups.

    ``taxon`` needs columns (taxid, rank, path); ``features`` needs
    (taxid, short, long, ass, ann) and optionally the additive composition
    columns (``n_ass_*``, ``n_reference``). ``root_taxid`` scopes the species
    universe to that subtree (the pipeline passes Eukaryota). Returns one row per
    taxon with columns (taxid, n_rows, c_*, s_*, *COMPOSITION_COLUMNS) in METRICS
    order, combining:

    - the **species rollup** — one row per ancestor clade, features summed up
      every species' lineage (``n_rows`` = species in the subtree); and
    - **below-species rows** — one row per featured infraspecific taxon
      (subspecies/strain/...), holding only its own directly-attached features
      with ``n_rows = 1``, never rolled into any ancestor.

    The two row-sets have disjoint taxids (an infraspecific taxon is never an
    ancestor of a species), so a plain vertical concat is exact.
    """
    features = _with_composition_defaults(features)
    clade = _species_rollup(taxon, features, root_taxid)
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
