"""Phase 1 build: NCBI taxdump -> ``taxon``; leaf features + taxonomy ->
``clade_features``. Loads Postgres and validates against Euka-Survey.

No ETE3, no ``precomputed_taxa``. Run it (with Postgres up) via:

    uv run --package eukahub-pipeline python -m eukahub_pipeline.build
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
from eukahub_pipeline.load import load_clade_features, load_taxon
from eukahub_pipeline.rollup import rollup_clades
from eukahub_pipeline.taxdump import build_paths, parse_names, parse_nodes
from eukahub_pipeline.validate import validate

log = logging.getLogger("eukahub.build")

DEFAULT_DB_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"
# Phase 1 bridge: leaf features come from the old Euka-Survey SQLite DB.
DEFAULT_LEAF_DB = "../Euka-Survey/eukaryotes.db"
DEFAULT_TAXDUMP_DIR = "data/taxdump"


def _taxon_copy_rows(
    nodes: dict[int, tuple[int, str]], names: dict[int, str], paths: dict[int, str]
) -> Iterator[tuple]:
    """Stream (taxid, name, rank, parent_id, path) tuples for COPY — a
    generator so the full tree is never materialized as a row list."""
    for taxid, (parent, rank) in nodes.items():
        yield (taxid, names.get(taxid, str(taxid)), rank, parent, paths[taxid])


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
    p = argparse.ArgumentParser(description="EukaHub Phase 1 build.")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DB_URL))
    p.add_argument("--leaf-db", default=os.environ.get("EUKAHUB_LEAF_DB", DEFAULT_LEAF_DB))
    p.add_argument(
        "--taxdump-dir", default=os.environ.get("EUKAHUB_TAXDUMP_DIR", DEFAULT_TAXDUMP_DIR)
    )
    p.add_argument("--skip-download", action="store_true", help="use an already-unpacked taxdump")
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

    with psycopg.connect(args.database_url) as conn:
        n_taxon = load_taxon(conn, _taxon_copy_rows(nodes, names, paths))
        log.info("Loaded %d taxon rows", n_taxon)
        del names  # not needed for the rollup

        taxon_df = _taxon_frame(nodes, paths)
        clade = rollup_clades(taxon_df, args.leaf_db)
        n_clade = load_clade_features(conn, clade)
        log.info("Loaded %d clade_features rows", n_clade)

        validate(conn, args.leaf_db)

    log.info("Phase 1 build finished in %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    raise SystemExit(main())
