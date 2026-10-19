"""Columns of the ``assembly`` table computed at build time: the species each
assembly belongs to, and how many annotations it has and their best BUSCO.

Stored so that the record lists and their downloads read them instead of looking
them up for every request.
"""

from __future__ import annotations

import polars as pl
from eukahub_core.taxonomy import UNIT_RANKS

from eukahub_pipeline.fetch_assemblies import ASSEMBLY_COLUMNS, assembly_number

ASSEMBLY_LINK_COLUMNS: tuple[str, ...] = ("species_taxid", "annotations", "best_busco")
# Every column of the `assembly` table, in schema order.
ASSEMBLY_TABLE_COLUMNS: tuple[str, ...] = ASSEMBLY_COLUMNS + ASSEMBLY_LINK_COLUMNS


def species_of(taxids: set[int], nodes: dict[int, tuple[int, str]]) -> dict[int, int]:
    """Each taxid's species: itself when it is a species or an informal species,
    else the nearest one above it; a taxon with neither counts as its own."""
    out: dict[int, int] = {}
    for taxid in taxids:
        node = taxid
        while True:
            parent, rank = nodes[node]
            if rank in UNIT_RANKS:
                out[taxid] = node
                break
            if parent == node or parent not in nodes:
                out[taxid] = taxid
                break
            node = parent
    return out


def with_assembly_links(
    assemblies: pl.DataFrame, annotations: pl.DataFrame, nodes: dict[int, tuple[int, str]]
) -> pl.DataFrame:
    """``assemblies`` with ``ASSEMBLY_LINK_COLUMNS`` added. Annotations name an
    assembly by any version of its GenBank or RefSeq accession, so they are matched
    by assembly number; ``nodes`` (taxid -> (parent, rank)) must hold every
    assembly's taxon."""
    species = species_of(set(assemblies["taxid"].to_list()), nodes)
    per_number = (
        annotations.filter(pl.col("assembly_accession").is_not_null())
        .group_by(assembly_number(pl.col("assembly_accession")).alias("_number"))
        .agg(
            pl.len().cast(pl.Int64).alias("annotations"),
            pl.col("busco_complete").max().alias("best_busco"),
        )
    )
    return (
        assemblies.with_columns(
            assembly_number(pl.col("assembly_accession")).alias("_number"),
            pl.col("taxid").replace_strict(species, return_dtype=pl.Int64).alias("species_taxid"),
        )
        .join(per_number, on="_number", how="left")
        .with_columns(pl.col("annotations").fill_null(0))
        .drop("_number")
        .select(ASSEMBLY_TABLE_COLUMNS)
    )
