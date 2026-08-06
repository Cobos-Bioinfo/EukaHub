"""Build: NCBI taxdump -> ``taxon``; fresh NCBI/Annotrieve/ENA fetches ->
per-record ``assembly`` / ``annotation`` tables + the ``clade_features`` rollup.

No ETE3, no ``precomputed_taxa``. The three sources are fetched (or reused from
parquet snapshots) up front, filtered to the taxonomy, loaded per-record, and
rolled up species-only. Run it (with Postgres up) via:

    uv run --package eukahub-pipeline python -m eukahub_pipeline.build

Reuse an unpacked taxdump with ``--skip-download``; re-fetch the live sources
(ignoring snapshots) with ``--refresh-sources``.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import psycopg

from eukahub_pipeline.download import download_taxdump
from eukahub_pipeline.fetch_annotations import ANNOTATION_COLUMNS, fetch_annotations
from eukahub_pipeline.fetch_assemblies import (
    ASSEMBLY_COLUMNS,
    EUKARYOTE_TXID,
    fetch_assemblies,
)
from eukahub_pipeline.fetch_reads import READS_COLUMNS, fetch_reads
from eukahub_pipeline.load import (
    load_annotation,
    load_assembly,
    load_clade_features,
    load_dataset_meta,
    load_taxon,
)
from eukahub_pipeline.rollup import assemble_leaf_features, rollup_from_frames
from eukahub_pipeline.snapshot import cached_frame
from eukahub_pipeline.taxdump import (
    ancestors,
    build_paths,
    descendants,
    parse_names,
    parse_nodes,
)
from eukahub_pipeline.validate import validate

log = logging.getLogger("eukahub.build")

DEFAULT_DB_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"
# Kept only for the validation printout (parity vs the old Euka-Survey numbers).
DEFAULT_LEAF_DB = "../Euka-Survey/eukaryotes.db"
DEFAULT_TAXDUMP_DIR = "data/taxdump"
DEFAULT_SOURCES_DIR = "data/sources"
# The schema DDL applied before loading, so the build works against a fresh,
# empty Postgres (e.g. the scheduled-rebuild CI service) with no separate init
# step. Every statement is idempotent (CREATE ... IF NOT EXISTS), so re-applying
# on the already-initialized dev DB is a no-op.
DEFAULT_SCHEMA_DIR = "infra/postgres/init"

# Parquet snapshot dtypes — key order mirrors each fetch module's *_COLUMNS.
_ASSEMBLY_SCHEMA: dict[str, pl.DataType] = {
    "assembly_accession": pl.Utf8,
    "taxid": pl.Int64,
    "assembly_level": pl.Utf8,
    "contig_n50": pl.Int64,
    "scaffold_n50": pl.Int64,
    "total_sequence_length": pl.Int64,
    "gc_percent": pl.Float64,
    "refseq_category": pl.Utf8,
    "release_date": pl.Utf8,
    "submitter": pl.Utf8,
    "source_database": pl.Utf8,
    "bioprojects": pl.List(pl.Utf8),
    "download_url": pl.Utf8,
}
_ANNOTATION_SCHEMA: dict[str, pl.DataType] = {
    "annotation_id": pl.Utf8,
    "assembly_accession": pl.Utf8,
    "taxid": pl.Int64,
    "source_database": pl.Utf8,
    "provider": pl.Utf8,
    "release_date": pl.Utf8,
    "gff_url": pl.Utf8,
    "gene_count": pl.Int64,
    "protein_coding_count": pl.Int64,
    "busco_complete": pl.Float64,
    "busco_single_copy": pl.Float64,
    "busco_duplicated": pl.Float64,
    "busco_lineage": pl.Utf8,
}
_READS_SCHEMA: dict[str, pl.DataType] = {
    "taxid": pl.Int64,
    "short": pl.Int64,
    "long": pl.Int64,
}

# Fail fast if a schema drifts from its fetch module's declared column set.
assert tuple(_ASSEMBLY_SCHEMA) == ASSEMBLY_COLUMNS
assert tuple(_ANNOTATION_SCHEMA) == ANNOTATION_COLUMNS
assert tuple(_READS_SCHEMA) == READS_COLUMNS


def _taxon_copy_rows(
    nodes: dict[int, tuple[int, str]], names: dict[int, str], paths: dict[int, str]
) -> Iterator[tuple]:
    """Stream (taxid, name, rank, parent_id, path) tuples for COPY — a
    generator so the full tree is never materialized as a row list."""
    for taxid, (parent, rank) in nodes.items():
        yield (taxid, names.get(taxid, str(taxid)), rank, parent, paths[taxid])


def _apply_schema(conn: psycopg.Connection, schema_dir: str) -> None:
    """Apply every ``*.sql`` in ``schema_dir`` (idempotent DDL) so the build can
    run against a fresh, empty Postgres. Skipped with a warning if the directory
    is absent (e.g. run from an unexpected CWD)."""
    d = Path(schema_dir)
    files = sorted(d.glob("*.sql"))
    if not files:
        log.warning("no schema SQL found in %s; skipping schema apply", d)
        return
    for f in files:
        conn.execute(f.read_text())
        log.info("applied schema %s", f.name)
    conn.commit()


def _taxon_frame(nodes: dict[int, tuple[int, str]], paths: dict[int, str]) -> pl.DataFrame:
    """Build the (taxid, rank, path) frame the rollup joins against."""
    taxids = list(nodes.keys())
    return pl.DataFrame(
        {
            "taxid": taxids,
            "rank": [nodes[t][1] for t in taxids],
            "path": [paths[t] for t in taxids],
        },
        schema={"taxid": pl.Int64, "rank": pl.Utf8, "path": pl.Utf8},
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="EukaHub build.")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DB_URL))
    p.add_argument("--leaf-db", default=os.environ.get("EUKAHUB_LEAF_DB", DEFAULT_LEAF_DB))
    p.add_argument(
        "--taxdump-dir", default=os.environ.get("EUKAHUB_TAXDUMP_DIR", DEFAULT_TAXDUMP_DIR)
    )
    p.add_argument(
        "--sources-dir",
        default=os.environ.get("EUKAHUB_SOURCES_DIR", DEFAULT_SOURCES_DIR),
        help="directory for the fetched-source parquet snapshots",
    )
    p.add_argument("--skip-download", action="store_true", help="use an already-unpacked taxdump")
    p.add_argument(
        "--refresh-sources",
        action="store_true",
        help="re-fetch the live sources, ignoring any parquet snapshots",
    )
    p.add_argument(
        "--schema-dir",
        default=os.environ.get("EUKAHUB_SCHEMA_DIR", DEFAULT_SCHEMA_DIR),
        help="directory of idempotent schema SQL applied before loading",
    )
    p.add_argument(
        "--skip-schema",
        action="store_true",
        help="assume the schema already exists (skip applying schema-dir)",
    )
    args = p.parse_args(argv)

    t0 = time.time()

    if not args.skip_download:
        download_taxdump(args.taxdump_dir)

    d = Path(args.taxdump_dir)
    log.info("Parsing taxdump in %s", d)
    nodes = parse_nodes(d / "nodes.dmp")
    names = parse_names(d / "names.dmp")
    log.info("Parsed %d nodes, %d scientific names", len(nodes), len(names))
    parents = {t: parent for t, (parent, _) in nodes.items()}
    paths = build_paths(parents)
    log.info("Built %d lineage paths", len(paths))

    # Scope the serving DB to Eukaryota. `taxon` would otherwise carry ~950k
    # Bacteria/Archaea/Viruses/unclassified nodes (a third of the tree) that the
    # Eukaryota-only app never surfaces, bloating the table and every dump. Keep
    # Eukaryota's whole subtree plus its ancestor spine (root + cellular
    # organisms) so lineage/breadcrumb queries resolve and the rollup's ancestor
    # rows (taxid 1 / 131567) still have a `taxon` row for their FK. Paths are
    # built from the full tree first, so kept nodes retain their real lineage
    # string. See docs/data-model.md.
    keep = descendants(parents, EUKARYOTE_TXID) | ancestors(parents, EUKARYOTE_TXID)
    nodes = {t: v for t, v in nodes.items() if t in keep}
    paths = {t: p for t, p in paths.items() if t in keep}
    log.info("Scoped taxonomy to Eukaryota: kept %d of %d nodes", len(nodes), len(parents))

    # Fetch (or reuse) the three sources — no DB connection needed for this.
    assemblies = cached_frame(
        "assemblies",
        lambda: fetch_assemblies(EUKARYOTE_TXID),
        _ASSEMBLY_SCHEMA,
        args.sources_dir,
        refresh=args.refresh_sources,
    )
    annotations = cached_frame(
        "annotations", fetch_annotations, _ANNOTATION_SCHEMA, args.sources_dir,
        refresh=args.refresh_sources,
    )
    reads = cached_frame(
        "reads", fetch_reads, _READS_SCHEMA, args.sources_dir, refresh=args.refresh_sources
    )

    taxon_df = _taxon_frame(nodes, paths)
    # Drop source rows on taxids absent from the taxonomy (merged/deleted NCBI
    # taxids); the per-record tables should never reference an unknown taxon.
    known = taxon_df.select("taxid")
    assemblies = assemblies.join(known, on="taxid", how="semi")
    annotations = annotations.join(known, on="taxid", how="semi")
    reads = reads.join(known, on="taxid", how="semi")
    log.info(
        "After taxonomy filter: %d assemblies, %d annotations, %d read taxa",
        assemblies.height, annotations.height, reads.height,
    )

    leaf = assemble_leaf_features(assemblies, annotations, reads)
    # Scope the rollup to Eukaryota — `taxon` holds the whole NCBI tree.
    clade = rollup_from_frames(taxon_df, leaf, root_taxid=EUKARYOTE_TXID)
    log.info("Rolled up into %d clade rows", clade.height)

    with psycopg.connect(args.database_url) as conn:
        if not args.skip_schema:
            _apply_schema(conn, args.schema_dir)
        n_taxon = load_taxon(conn, _taxon_copy_rows(nodes, names, paths))
        log.info("Loaded %d taxon rows", n_taxon)
        n_ass = load_assembly(conn, assemblies)
        n_ann = load_annotation(conn, annotations)
        log.info("Loaded %d assembly + %d annotation rows", n_ass, n_ann)
        n_clade = load_clade_features(conn, clade)
        log.info("Loaded %d clade_features rows", n_clade)

        # Gate on the invariants BEFORE stamping — a broken build raises here and
        # never records a (misleading) "updated" timestamp.
        validate(conn, args.leaf_db)

        load_dataset_meta(
            conn,
            taxon_count=n_taxon,
            assembly_count=n_ass,
            annotation_count=n_ann,
            clade_count=n_clade,
        )
        log.info("Stamped dataset_meta (built_at = now)")

    log.info("Build finished in %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(main())
