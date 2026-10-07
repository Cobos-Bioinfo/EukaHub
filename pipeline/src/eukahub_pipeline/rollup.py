"""Roll per-taxon features up every lineage into per-clade rollups.

A taxon's lineage is its ``path`` split on dots, so Polars does the fan-out:
each row is exploded into its ancestors, then grouped by ancestor and summed
(docs/decisions.md: Polars for this step).
"""

from __future__ import annotations

import logging

import polars as pl
from eukahub_core.metrics import (
    ASSEMBLY_LEVEL_TO_COLUMN,
    COMPOSITION_COLUMNS,
    COVERAGE_KEYS,
    METRIC_KEYS,
    QUALITY_KEYS,
    QUALITY_STATS,
    TOTAL_KEYS,
)
from eukahub_core.taxonomy import INFORMAL_SPECIES_RANK, SPECIES_RANK, UNIT_RANKS

log = logging.getLogger("eukahub.rollup")

# The per-taxid leaf inputs the fan-out consumes: raw read counts + assembly and
# annotation totals + the additive assembly-composition columns.
_LEAF_COUNT_COLUMNS: tuple[str, ...] = ("ass", "ann", "short", "long", *COMPOSITION_COLUMNS)
_OUTPUT_COLUMNS: tuple[str, ...] = (
    "taxid",
    "n_rows",
    *COVERAGE_KEYS,
    *TOTAL_KEYS,
    *COMPOSITION_COLUMNS,
)


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
    per_reads = reads.select("taxid", pl.col("short").cast(pl.Int64), pl.col("long").cast(pl.Int64))

    leaf = (
        per_assembly.join(per_annotation, on="taxid", how="full", coalesce=True)
        .join(per_reads, on="taxid", how="full", coalesce=True)
        .with_columns([pl.col(c).fill_null(0).cast(pl.Int64) for c in _LEAF_COUNT_COLUMNS])
    )
    log.info("Assembled leaf features for %d taxa", leaf.height)
    return leaf


def carrying_taxids(features: pl.DataFrame) -> set[int]:
    """Taxids with at least one record or run attached directly."""
    has_data = pl.any_horizontal(pl.col(c) > 0 for c in ("ass", "ann", "short", "long"))
    return set(features.filter(has_data)["taxid"].to_list())


def _collect(lf: pl.LazyFrame) -> pl.DataFrame:
    """Collect, preferring the streaming engine (bounds memory on the exploded
    intermediate), with fallbacks across Polars versions."""
    try:
        return lf.collect(engine="streaming")
    except TypeError:
        try:
            return lf.collect(streaming=True)
        except TypeError:
            return lf.collect()


def _ancestors(frame: pl.LazyFrame) -> pl.LazyFrame:
    """One row per (ancestor-or-self, row) pair, with the ancestor as ``taxid``."""
    return (
        frame.with_columns(pl.col("path").str.split(".").alias("anc"))
        .explode("anc", empty_as_null=True)
        .with_columns(pl.col("anc").cast(pl.Int64).alias("taxid"))
        .drop("anc", "path")
    )


def _subtree_totals(taxon: pl.DataFrame, features: pl.DataFrame) -> pl.DataFrame:
    """``s_*`` and composition per taxon: everything attached anywhere in its subtree."""
    own = features.join(taxon.select("taxid", "path"), on="taxid", how="inner").select(
        "path",
        pl.col("ass").alias("s_ass"),
        pl.col("ann").alias("s_ann"),
        (pl.col("short") + pl.col("long")).alias("s_rna"),
        pl.col("long").alias("s_lng"),
        *COMPOSITION_COLUMNS,
    )
    summed = [*TOTAL_KEYS, *COMPOSITION_COLUMNS]
    return _collect(_ancestors(own.lazy()).group_by("taxid").agg([pl.col(c).sum() for c in summed]))


def _species_counts(taxon: pl.DataFrame, totals: pl.DataFrame) -> pl.DataFrame:
    """``n_rows`` and ``c_*`` per taxon: its species, and those whose subtree has
    each resource (so data on a subspecies counts for its species)."""
    species = (
        taxon.filter(pl.col("rank") == SPECIES_RANK)
        .select("taxid", "path")
        .join(totals.select("taxid", *TOTAL_KEYS), on="taxid", how="left")
        .select(
            "path",
            *[
                (pl.col(f"s_{k}").fill_null(0) > 0).cast(pl.Int64).alias(f"c_{k}")
                for k in METRIC_KEYS
            ],
        )
    )
    return _collect(
        _ancestors(species.lazy())
        .group_by("taxid")
        .agg(pl.len().cast(pl.Int64).alias("n_rows"), *[pl.col(c).sum() for c in COVERAGE_KEYS])
    )


def _unit_taxids(taxon: pl.DataFrame, candidates: pl.DataFrame) -> pl.DataFrame:
    """The candidates that are an informal species or sit below a species or an
    informal species: single units rather than clades of species."""
    ranked = candidates.join(taxon.select("taxid", "rank", "path"), on="taxid", how="inner")
    unit_ids = taxon.filter(pl.col("rank").is_in(UNIT_RANKS)).select(pl.col("taxid").alias("anc"))
    below = (
        ranked.select("taxid", pl.col("path").str.split(".").alias("anc"))
        .explode("anc", empty_as_null=True)
        .with_columns(pl.col("anc").cast(pl.Int64))
        .filter(pl.col("anc") != pl.col("taxid"))
        .join(unit_ids, on="anc", how="semi")
        .select("taxid")
    )
    informal = ranked.filter(pl.col("rank") == INFORMAL_SPECIES_RANK).select("taxid")
    return pl.concat([below, informal]).unique()


def _with_composition_defaults(features: pl.DataFrame) -> pl.DataFrame:
    """Ensure the additive composition columns exist (0 when a caller passes the
    minimal ``{taxid, short, long, ass, ann}`` frame, as the unit tests do)."""
    missing = [c for c in COMPOSITION_COLUMNS if c not in features.columns]
    if missing:
        features = features.with_columns([pl.lit(0, dtype=pl.Int64).alias(c) for c in missing])
    return features


def rollup_from_frames(
    taxon: pl.DataFrame, features: pl.DataFrame, root_taxid: int | None = None
) -> pl.DataFrame:
    """Roll per-taxon features into one row per clade.

    ``taxon`` needs (taxid, rank, path); ``features`` needs (taxid, short, long,
    ass, ann) and optionally the composition columns. ``root_taxid`` limits the
    rollup to that subtree. For every taxon with species or data below it:

    - ``s_*`` and the composition columns sum every record in its subtree,
      whatever the rank it is attached to;
    - ``n_rows`` counts its species (rank ``species``), with or without data;
    - ``c_*`` counts the species whose own subtree has that resource.

    An informal species, or a taxon below a species, is one unit instead:
    ``n_rows = 1`` and ``c_* = 1`` when it has that resource. Its data still
    counts in the totals of every taxon above it.
    """
    features = _with_composition_defaults(features)
    if root_taxid is not None:
        taxon = taxon.filter(pl.col("path").str.split(".").list.contains(str(root_taxid)))

    totals = _subtree_totals(taxon, features)
    counts = _species_counts(taxon, totals)
    clade = counts.join(totals, on="taxid", how="full", coalesce=True).with_columns(
        [pl.col(c).fill_null(0).cast(pl.Int64) for c in _OUTPUT_COLUMNS[1:]]
    )

    units = _unit_taxids(taxon, clade.filter(pl.col("n_rows") == 0).select("taxid"))
    is_unit = pl.col("taxid").is_in(units["taxid"].implode())
    clade = clade.with_columns(
        pl.when(is_unit).then(1).otherwise(pl.col("n_rows")).alias("n_rows"),
        *[
            pl.when(is_unit)
            .then((pl.col(f"s_{k}") > 0).cast(pl.Int64))
            .otherwise(pl.col(f"c_{k}"))
            .alias(f"c_{k}")
            for k in METRIC_KEYS
        ],
    )
    return clade.select(_OUTPUT_COLUMNS)


def stats_from_records(
    taxon: pl.DataFrame,
    records: dict[str, pl.DataFrame],
    root_taxid: int | None = None,
) -> pl.DataFrame:
    """``QUALITY_STATS`` of every clade over the records on or below it.

    ``taxon`` needs (taxid, path); ``records`` maps each stat's ``source`` table
    (``assembly``, ``annotation``) to its record frame. Every record is fanned out
    to its ancestors, as in the rollup, and each clade takes the median or maximum
    of its records' values, nulls ignored, as Postgres' ``percentile_cont(0.5)`` and
    ``max`` do. One row per clade with at least one record: ``taxid`` then one column
    per stat key, null when none of its records has that value. ``root_taxid``
    limits it to that subtree, like ``rollup_from_frames``.
    """
    if root_taxid is not None:
        taxon = taxon.filter(pl.col("path").str.split(".").list.contains(str(root_taxid)))
    paths = taxon.select("taxid", "path")
    per_source = []
    for source, frame in records.items():
        source_stats = [q for q in QUALITY_STATS if q.source == source]
        values = frame.join(paths, on="taxid", how="inner").select(
            "path", *[pl.col(q.column).cast(pl.Float64).alias(q.key) for q in source_stats]
        )
        per_source.append(
            _collect(
                _ancestors(values.lazy())
                .group_by("taxid")
                .agg(
                    pl.col(q.key).median() if q.agg == "median" else pl.col(q.key).max()
                    for q in source_stats
                )
            )
        )
    stats = per_source[0]
    for frame in per_source[1:]:
        stats = stats.join(frame, on="taxid", how="full", coalesce=True)
    return stats.select("taxid", *QUALITY_KEYS).sort("taxid")

