"""Build: NCBI taxdump -> ``taxon``; fresh NCBI/Annotrieve/ENA fetches ->
per-record ``assembly`` / ``annotation`` tables + the ``clade_features`` rollup and
the per-clade quality stats (``clade_stats``).

No ETE3, no ``precomputed_taxa``. The three sources are fetched (or reused from
parquet snapshots) up front and filtered to the taxonomy; placeholder taxa without
data are dropped; records are loaded per-record and rolled up every lineage. Run it
(with Postgres up) via:

    uv run --package eukahub-pipeline python -m eukahub_pipeline.build

Reuse an unpacked taxdump with ``--skip-download``; re-fetch the live sources
(ignoring snapshots) with ``--refresh-sources``. ``--previous-counts`` compares the
build with the previous Release's counts, which ``--counts-out`` writes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import psycopg
from eukahub_core.taxonomy import EUKARYOTA_TAXID

from eukahub_pipeline.download import download_taxdump
from eukahub_pipeline.fetch_annotations import ANNOTATION_COLUMNS, fetch_annotations
from eukahub_pipeline.fetch_assemblies import (
    ASSEMBLY_COLUMNS,
    DatasetsCLIFailed,
    drop_duplicate_assemblies,
    fetch_assemblies,
)
from eukahub_pipeline.fetch_reads import READS_COLUMNS, fetch_reads
from eukahub_pipeline.load import (
    load_annotation,
    load_assembly,
    load_clade_features,
    load_clade_stats,
    load_dataset_meta,
    load_taxon,
)
from eukahub_pipeline.placeholders import orphans_below_species, prune_placeholders
from eukahub_pipeline.rollup import (
    assemble_leaf_features,
    carrying_taxids,
    rollup_from_frames,
    stats_from_records,
)
from eukahub_pipeline.snapshot import cached_frame
from eukahub_pipeline.sources import load_sources
from eukahub_pipeline.taxdump import (
    ancestors,
    build_paths,
    descendants,
    parse_names,
    parse_nodes,
)
from eukahub_pipeline.validate import check_against_previous, release_counts, validate

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
    """Stream (taxid, name, rank, parent_id, path) tuples for COPY, sorted by path
    so that each subtree's rows sit together on disk and a subtree scan reads only
    its own pages (NCBI's file order scatters them across the table)."""
    for taxid in sorted(nodes, key=paths.__getitem__):
        parent, rank = nodes[taxid]
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
    p.add_argument(
        "--previous-counts",
        type=Path,
        help="the previous Release's counts (JSON); fail if a count fell sharply since",
    )
    p.add_argument(
        "--accept-drops",
        action="store_true",
        help="log the counts that fell since the previous Release instead of failing",
    )
    p.add_argument("--counts-out", type=Path, help="write this build's counts here (JSON)")
    args = p.parse_args(argv)
    try:
        sources = load_sources(os.environ)
    except ValueError as e:
        p.error(str(e))
    for name in ("taxdump", "ena", "annotrieve"):
        source = getattr(sources, name)
        log.info("Source %s: %s (timeout %gs)", name, source.url, source.timeout)

    t0 = time.time()

    if not args.skip_download:
        download_taxdump(args.taxdump_dir, sources.taxdump)

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
    keep = descendants(parents, EUKARYOTA_TAXID) | ancestors(parents, EUKARYOTA_TAXID)
    nodes = {t: v for t, v in nodes.items() if t in keep}
    paths = {t: p for t, p in paths.items() if t in keep}
    log.info("Scoped taxonomy to Eukaryota: kept %d of %d nodes", len(nodes), len(parents))

    # Fetch (or reuse) the three sources — no DB connection needed for this.
    assemblies = cached_frame(
        "assemblies",
        lambda: fetch_assemblies(EUKARYOTA_TAXID),
        _ASSEMBLY_SCHEMA,
        args.sources_dir,
        refresh=args.refresh_sources,
        retry_on=(DatasetsCLIFailed,),
    )
    n_fetched = assemblies.height
    assemblies = drop_duplicate_assemblies(assemblies)
    log.info("Dropped %d duplicate assembly records", n_fetched - assemblies.height)
    annotations = cached_frame(
        "annotations",
        lambda: fetch_annotations(sources.annotrieve),
        _ANNOTATION_SCHEMA,
        args.sources_dir,
        refresh=args.refresh_sources,
    )
    reads = cached_frame(
        "reads",
        lambda: fetch_reads(sources.ena),
        _READS_SCHEMA,
        args.sources_dir,
        refresh=args.refresh_sources,
    )

    # Drop source rows on taxids absent from the taxonomy (merged/deleted NCBI
    # taxids); the per-record tables should never reference an unknown taxon.
    known = pl.DataFrame({"taxid": list(nodes)}, schema={"taxid": pl.Int64})
    assemblies = assemblies.join(known, on="taxid", how="semi")
    annotations = annotations.join(known, on="taxid", how="semi")
    reads = reads.join(known, on="taxid", how="semi")
    log.info(
        "After taxonomy filter: %d assemblies, %d annotations, %d read taxa",
        assemblies.height, annotations.height, reads.height,
    )
    leaf = assemble_leaf_features(assemblies, annotations, reads)

    nodes, pruned = prune_placeholders(nodes, names, carrying_taxids(leaf))
    paths = {t: paths[t] for t in nodes}
    log.info(
        "Species: %d formal, %d informal with data kept; %d placeholder taxa without data dropped",
        pruned.formal_species, pruned.informal_kept, pruned.dropped,
    )
    orphans = orphans_below_species(nodes)
    if orphans:
        log.warning(
            "%d below-species taxa have no species above them: %s",
            len(orphans), ", ".join(f"{t} {names.get(t, '')}" for t in orphans[:20]),
        )

    taxon_frame = _taxon_frame(nodes, paths)
    clade = rollup_from_frames(taxon_frame, leaf, root_taxid=EUKARYOTA_TAXID)
    log.info("Rolled up into %d clade rows", clade.height)
    stats = stats_from_records(
        taxon_frame,
        {"assembly": assemblies, "annotation": annotations},
        root_taxid=EUKARYOTA_TAXID,
    )
    log.info("Computed quality stats for %d clades", stats.height)

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
        log.info("Loaded %d clade_stats rows", load_clade_stats(conn, stats))

        # Gate on the invariants BEFORE stamping — a broken build raises here and
        # never records a (misleading) "updated" timestamp.
        validate(conn, args.leaf_db)
        counts = release_counts(conn)
        if args.previous_counts:
            previous = json.loads(args.previous_counts.read_text())
            check_against_previous(counts, previous, accept_drops=args.accept_drops)

        load_dataset_meta(
            conn,
            taxon_count=n_taxon,
            assembly_count=n_ass,
            annotation_count=n_ann,
            clade_count=n_clade,
        )
        log.info("Stamped dataset_meta (built_at = now)")

    if args.counts_out:
        args.counts_out.write_text(json.dumps(counts, indent=2) + "\n")
        log.info("Wrote the counts to %s", args.counts_out)

    log.info("Build finished in %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(main())
