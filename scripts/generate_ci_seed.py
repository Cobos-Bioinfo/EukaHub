"""Generate ``api/tests/seed.sql`` — a compact, self-consistent slice of the
serving DB so the DB-backed API tests can run in CI (see docs/roadmap.md).

Why a slice and not the real dataset: the production DB is ~2.5 GB and the
pipeline that builds it needs the network + a 500 MB taxdump. CI only needs to
catch *code / query* regressions, so a few hundred rows that preserve every
structural invariant the tests assert are enough; data-scale correctness is
validated at build time.

What it produces (all public NCBI data, no secrets):

- ``taxon``            the real ancestor chain of every anchor taxon (so
                       breadcrumbs, ``ltree`` subtree/ancestor queries, and
                       ``parent_id`` adjacency are all closed and correct), plus
                       Eukaryota's 21 real direct children (the tree/children
                       tests) and a minimal Bacteria -> E. coli branch (the
                       search-scope test asserts E. coli is excluded).
- ``assembly`` /       real per-record rows for the anchor species, capped for
  ``annotation``       the data-rich ones so the file stays tiny.
- ``clade_features``   **recomputed** for exactly this slice via the pipeline's
                       own rollup, scoped to Eukaryota — so ``n_rows`` and every
                       aggregate is exact and consistent with the sliced records
                       (reads, which have no per-record table, are carried over
                       from the production rollup's leaf values).

Run it against the full local serving DB (docker-compose Postgres) and commit
the result. Re-run only when the schema or the needed taxids change:

    uv run --package eukahub-pipeline python scripts/generate_ci_seed.py

Point it elsewhere with ``--source-url``; write elsewhere with ``--out``.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import polars as pl
import psycopg
from eukahub_core.metrics import clade_feature_columns
from eukahub_pipeline.fetch_annotations import ANNOTATION_COLUMNS
from eukahub_pipeline.fetch_assemblies import ASSEMBLY_COLUMNS
from eukahub_pipeline.rollup import assemble_leaf_features, rollup_from_frames

DEFAULT_SOURCE_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "api" / "tests" / "seed.sql"

EUKARYOTA_TAXID = 2759

# Record-bearing anchor taxa, chosen so the slice satisfies every test invariant
# (see the module docstring). Real NCBI taxids; each is validated at run time.
#   Primates: Homo sapiens (+ its 2 subspecies), Pan troglodytes
#   Carnivora: Canis lupus (+ subspecies familiaris, the infraspecific-with-data
#              case), Felis catus
#   Rodentia: Mus musculus
#   Arthropoda (a 2nd phylum under Eukaryota, for real breakdown sorting):
#              Drosophila melanogaster
#   Bacteria (outside Eukaryota, for the search-scope exclusion test): E. coli
ANCHOR_TAXIDS: tuple[int, ...] = (
    9606,    # Homo sapiens (species)
    63221,   # Homo sapiens neanderthalensis (subspecies, childless)
    741158,  # Homo sapiens subsp. 'Denisova' (subspecies, childless)
    9598,    # Pan troglodytes (species)
    9612,    # Canis lupus (species)
    9615,    # Canis lupus familiaris (subspecies, carries assemblies)
    9685,    # Felis catus (species)
    10090,   # Mus musculus (species)
    7227,    # Drosophila melanogaster (species)
    562,     # Escherichia coli (species, Bacteria — outside Eukaryota)
)

# Per-taxid record cap for the data-rich anchors, so the file stays small. Human
# must keep > 100 assemblies and > 10 annotations (test_records.py). Others are
# small enough to include whole.
ASSEMBLY_CAP: dict[int, int] = {9606: 120, 7227: 20, 10090: 20}
ANNOTATION_CAP: dict[int, int] = {9606: 20, 10090: 20}


# --------------------------------------------------------------------------- #
# Slice selection
# --------------------------------------------------------------------------- #
def select_slice(conn: psycopg.Connection) -> pl.DataFrame:
    """Return the ``taxon`` rows for the slice: (taxid, name, rank, parent_id,
    path). The set is the ancestor-closure of the anchor taxa (guaranteeing
    complete lineages + ``parent_id`` closure) plus Eukaryota's 21 direct
    children (the children/tree tests)."""
    taxids: set[int] = set()

    # Ancestor closure: every taxid on each anchor's root->node path.
    for (path,) in conn.execute(
        "SELECT path::text FROM taxon WHERE taxid = ANY(%s)", (list(ANCHOR_TAXIDS),)
    ).fetchall():
        taxids.update(int(x) for x in path.split("."))

    # Eukaryota's real direct children (their paths add nothing new but the nodes
    # themselves must exist as rows for the children endpoint to list them).
    for (child,) in conn.execute(
        "SELECT taxid FROM taxon WHERE parent_id = %s AND taxid <> parent_id",
        (EUKARYOTA_TAXID,),
    ).fetchall():
        taxids.add(child)

    rows = conn.execute(
        "SELECT taxid, name, rank, parent_id, path::text "
        "FROM taxon WHERE taxid = ANY(%s) ORDER BY taxid",
        (list(taxids),),
    ).fetchall()
    return pl.DataFrame(
        rows,
        schema=["taxid", "name", "rank", "parent_id", "path"],
        orient="row",
    )


def fetch_records(
    conn: psycopg.Connection, table: str, columns: tuple[str, ...],
    taxids: list[int], caps: dict[int, int], order_by: str,
) -> list[tuple]:
    """Fetch per-record rows for ``taxids`` from ``table`` (columns in schema
    order), keeping at most ``caps[taxid]`` per taxon — the newest/best first,
    matching the endpoints' default sort so the retained rows are the ones a
    reader would actually see."""
    select = ", ".join(columns)
    rows = conn.execute(
        f"SELECT {select} FROM {table} WHERE taxid = ANY(%s) "
        f"ORDER BY taxid, {order_by}",
        (taxids,),
    ).fetchall()

    kept: list[tuple] = []
    seen: dict[int, int] = {}
    taxid_idx = columns.index("taxid")
    for row in rows:
        tx = row[taxid_idx]
        cap = caps.get(tx)
        n = seen.get(tx, 0)
        if cap is not None and n >= cap:
            continue
        seen[tx] = n + 1
        kept.append(row)
    return kept


def build_clade_features(
    taxon: pl.DataFrame, conn: psycopg.Connection,
    assemblies: list[tuple], annotations: list[tuple],
) -> pl.DataFrame:
    """Recompute ``clade_features`` for the slice via the pipeline's own rollup.

    Leaf inputs are rebuilt from the slice's *own* per-record rows (so the
    aggregates match the seeded assemblies/annotations exactly), except reads —
    which have no per-record table — whose per-species leaf counts are read back
    from the production rollup (a species' rolled-up ``s_rna``/``s_lng`` is its
    own leaf value, since a species' subtree is itself)."""
    acol = {c: i for i, c in enumerate(ASSEMBLY_COLUMNS)}
    assemblies_pl = pl.DataFrame(
        {
            "taxid": [r[acol["taxid"]] for r in assemblies],
            "assembly_level": [r[acol["assembly_level"]] for r in assemblies],
            "refseq_category": [r[acol["refseq_category"]] for r in assemblies],
        },
        schema={"taxid": pl.Int64, "assembly_level": pl.Utf8, "refseq_category": pl.Utf8},
    )
    ncol = {c: i for i, c in enumerate(ANNOTATION_COLUMNS)}
    annotations_pl = pl.DataFrame(
        {"taxid": [r[ncol["taxid"]] for r in annotations]},
        schema={"taxid": pl.Int64},
    )

    # Reads: per-species (and per-infraspecific) leaf counts from the prod rollup.
    reads_rows = conn.execute(
        "SELECT taxid, s_rna - s_lng AS short, s_lng AS long FROM clade_features "
        "WHERE taxid = ANY(%s) AND (s_rna > 0 OR s_lng > 0)",
        (taxon["taxid"].to_list(),),
    ).fetchall()
    reads_pl = pl.DataFrame(
        reads_rows, schema={"taxid": pl.Int64, "short": pl.Int64, "long": pl.Int64},
        orient="row",
    )

    leaf = assemble_leaf_features(assemblies_pl, annotations_pl, reads_pl)
    taxon_for_rollup = taxon.select("taxid", "rank", "path")
    return rollup_from_frames(taxon_for_rollup, leaf, root_taxid=EUKARYOTA_TAXID)


# --------------------------------------------------------------------------- #
# SQL emission
# --------------------------------------------------------------------------- #
def sql_literal(value: object) -> str:
    """Render one Python value as a SQL literal for the seed file."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):  # before int — bool is an int subclass
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dt.date):
        return f"'{value.isoformat()}'"
    if isinstance(value, (list, tuple)):  # TEXT[] (e.g. bioprojects)
        inner = ", ".join(sql_literal(v) for v in value)
        return f"ARRAY[{inner}]::text[]"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def emit_insert(out: list[str], table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    """Append a multi-row INSERT (chunked) for ``rows`` into ``out``."""
    if not rows:
        return
    collist = ", ".join(columns)
    chunk = 100
    for start in range(0, len(rows), chunk):
        out.append(f"INSERT INTO {table} ({collist}) VALUES")
        values = [
            "  (" + ", ".join(sql_literal(v) for v in row) + ")"
            for row in rows[start : start + chunk]
        ]
        out.append(",\n".join(values) + ";")


def generate(source_url: str, out_path: Path) -> None:
    with psycopg.connect(source_url) as conn:
        taxon = select_slice(conn)
        slice_taxids = taxon["taxid"].to_list()

        assemblies = fetch_records(
            conn, "assembly", ASSEMBLY_COLUMNS, slice_taxids, ASSEMBLY_CAP,
            order_by="release_date DESC NULLS LAST, assembly_accession",
        )
        annotations = fetch_records(
            conn, "annotation", ANNOTATION_COLUMNS, slice_taxids, ANNOTATION_CAP,
            order_by="busco_complete DESC NULLS LAST, annotation_id",
        )
        clade = build_clade_features(taxon, conn, assemblies, annotations)

    n_species = taxon.filter(pl.col("rank") == "species").height
    counts = (
        f"-- taxon={taxon.height} clade_features={clade.height} "
        f"assembly={len(assemblies)} annotation={len(annotations)}"
    )
    lines: list[str] = [
        "-- EukaHub CI test seed — GENERATED by scripts/generate_ci_seed.py.",
        "-- A compact, self-consistent slice of the serving DB for the DB-backed",
        "-- API tests. Do not edit by hand; re-run the generator instead.",
        counts,
        "",
        "BEGIN;",
        "TRUNCATE annotation, assembly, clade_features, taxon RESTART IDENTITY CASCADE;",
        "",
    ]

    clade_cols = ("taxid", "n_rows", *clade_feature_columns())
    emit_insert(lines, "taxon",
                ("taxid", "name", "rank", "parent_id", "path"),
                taxon.rows())
    lines.append("")
    emit_insert(lines, "clade_features", clade_cols,
                clade.select(list(clade_cols)).rows())
    lines.append("")
    emit_insert(lines, "assembly", ASSEMBLY_COLUMNS, assemblies)
    lines.append("")
    emit_insert(lines, "annotation", ANNOTATION_COLUMNS, annotations)
    lines.append("")
    lines.append("COMMIT;")
    lines.append("")

    out_path.write_text("\n".join(lines))
    print(
        f"Wrote {out_path} — taxon={taxon.height} (species={n_species}) "
        f"clade_features={clade.height} assembly={len(assemblies)} "
        f"annotation={len(annotations)}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-url", default=DEFAULT_SOURCE_URL,
                   help="full serving DB to slice from")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="output SQL path (default: api/tests/seed.sql)")
    args = p.parse_args()
    generate(args.source_url, args.out)


if __name__ == "__main__":
    main()
