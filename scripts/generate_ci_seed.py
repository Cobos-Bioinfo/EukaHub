"""Generate ``api/tests/seed.sql`` — a compact, self-consistent slice of the
serving DB so the DB-backed API tests can run in CI (see CONTRIBUTING.md).

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
                       tests).
- ``assembly`` /       real per-record rows for the anchor species, capped for
  ``annotation``       the data-rich ones so the file stays tiny; each assembly's
                       species and annotation count recomputed from the slice.
- ``rna_seq_runs`` /   real run groups of the slice's taxa, capped per taxon, and
  ``study``            the studies they name with their parents.
- ``taxon_merged``     a few real merged taxids of the slice's taxa.
- ``clade_features``   **recomputed** for exactly this slice via the pipeline's
                       own rollup, scoped to Eukaryota — so ``n_rows`` and every
                       aggregate is exact and consistent with the sliced records
                       and run groups.
- ``clade_stats``      recomputed the same way from the sliced records.

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
from eukahub_core.metrics import QUALITY_KEYS, clade_feature_columns
from eukahub_core.taxonomy import EUKARYOTA_TAXID
from eukahub_pipeline.build import _studies_to_keep
from eukahub_pipeline.enrich import ASSEMBLY_TABLE_COLUMNS, with_assembly_links
from eukahub_pipeline.fetch_annotations import ANNOTATION_COLUMNS
from eukahub_pipeline.fetch_assemblies import ASSEMBLY_COLUMNS
from eukahub_pipeline.fetch_reads import RUN_GROUP_COLUMNS, STUDY_COLUMNS
from eukahub_pipeline.load import TAXON_COLUMNS
from eukahub_pipeline.rollup import (
    assemble_leaf_features,
    rollup_from_frames,
    runs_per_taxon,
    stats_from_records,
)

DEFAULT_SOURCE_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "api" / "tests" / "seed.sql"


# Record-bearing anchor taxa, chosen so the slice satisfies every test invariant
# (see the module docstring). Real NCBI taxids; select_slice fails if one is missing.
#   Primates: Homo sapiens (+ its 2 subspecies), Pan troglodytes
#   Carnivora: Canis lupus (+ subspecies familiaris, the infraspecific-with-data
#              case), Felis catus
#   Rodentia: Mus musculus
#   Arthropoda (a 2nd phylum under Eukaryota, for real breakdown sorting):
#              Drosophila melanogaster
#   Papio: a cross between two baboon species, the informal-species case
#   Homo heidelbergensis: a species without data, so the gaps tests find gaps
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
    208510,  # Papio cynocephalus x Papio anubis (informal species, carries assemblies)
    1425170,  # Homo heidelbergensis (species without data: every resource has a gap)
)

# Per-taxid record cap for the data-rich anchors, so the file stays small. Human
# must keep > 100 assemblies and > 10 annotations (test_records.py). Others are
# small enough to include whole.
ASSEMBLY_CAP: dict[int, int] = {9606: 120, 7227: 20, 10090: 20}
ANNOTATION_CAP: dict[int, int] = {9606: 20, 10090: 20}
# Run groups kept per taxon (those with the most runs), and merged taxids in all.
RUN_GROUP_CAP = 12
MERGED_CAP = 10


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
    rows = conn.execute(
        "SELECT taxid, path::text FROM taxon WHERE taxid = ANY(%s)", (list(ANCHOR_TAXIDS),)
    ).fetchall()
    missing = set(ANCHOR_TAXIDS) - {taxid for taxid, _ in rows}
    if missing:
        raise SystemExit(f"anchor taxa missing from the source DB: {sorted(missing)}")
    for _taxid, path in rows:
        taxids.update(int(x) for x in path.split("."))

    # Eukaryota's real direct children (their paths add nothing new but the nodes
    # themselves must exist as rows for the children endpoint to list them).
    for (child,) in conn.execute(
        "SELECT taxid FROM taxon WHERE parent_id = %s AND taxid <> parent_id",
        (EUKARYOTA_TAXID,),
    ).fetchall():
        taxids.add(child)

    rows = conn.execute(
        f"SELECT {', '.join(TAXON_COLUMNS)} FROM taxon WHERE taxid = ANY(%s) ORDER BY taxid",
        (list(taxids),),
    ).fetchall()
    return pl.DataFrame(
        [(*row[:-1], str(row[-1])) for row in rows], schema=list(TAXON_COLUMNS), orient="row"
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
    taxon: pl.DataFrame, assemblies: list[tuple], annotations: list[tuple],
    run_groups: pl.DataFrame,
) -> pl.DataFrame:
    """Recompute ``clade_features`` for the slice via the pipeline's own rollup,
    from the slice's own records and run groups, so the aggregates match them
    exactly."""
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

    leaf = assemble_leaf_features(assemblies_pl, annotations_pl, runs_per_taxon(run_groups))
    taxon_for_rollup = taxon.select("taxid", "rank", "path")
    return rollup_from_frames(taxon_for_rollup, leaf, root_taxid=EUKARYOTA_TAXID)


def link_assemblies(
    taxon: pl.DataFrame, assemblies: list[tuple], annotations: list[tuple]
) -> list[tuple]:
    """The assembly rows with ``enrich``'s columns, computed from the slice."""
    frame = pl.DataFrame(
        assemblies,
        schema={c: pl.Object for c in ASSEMBLY_COLUMNS} | {"assembly_accession": pl.Utf8, "taxid": pl.Int64},
        orient="row",
    )
    ncol = {c: i for i, c in enumerate(ANNOTATION_COLUMNS)}
    annotation_frame = pl.DataFrame(
        {
            "assembly_accession": [r[ncol["assembly_accession"]] for r in annotations],
            "busco_complete": [r[ncol["busco_complete"]] for r in annotations],
        },
        schema={"assembly_accession": pl.Utf8, "busco_complete": pl.Float64},
    )
    nodes = {t: (parent, rank) for t, parent, rank in taxon.select("taxid", "parent_id", "rank").rows()}
    return with_assembly_links(frame, annotation_frame, nodes).rows()


def fetch_run_groups(conn: psycopg.Connection, taxids: list[int]) -> pl.DataFrame:
    """The run groups of these taxa, at most ``RUN_GROUP_CAP`` per taxon (most runs first)."""
    rows = conn.execute(
        f"SELECT {', '.join(RUN_GROUP_COLUMNS)} FROM ("
        f"SELECT *, row_number() OVER (PARTITION BY taxid ORDER BY runs DESC, study_accession, "
        "center_name, first_public_year, long_read) AS n FROM rna_seq_runs WHERE taxid = ANY(%s)"
        ") g WHERE n <= %s ORDER BY taxid, long_read, runs DESC, study_accession",
        (taxids, RUN_GROUP_CAP),
    ).fetchall()
    return pl.DataFrame(
        rows,
        schema={
            "taxid": pl.Int64, "study_accession": pl.Utf8, "long_read": pl.Boolean,
            "center_name": pl.Utf8, "first_public_year": pl.Int16, "runs": pl.Int64,
            "bases": pl.Int64, "reads": pl.Int64,
        },
        orient="row",
    )


def fetch_studies(conn: psycopg.Connection, run_groups: pl.DataFrame) -> pl.DataFrame:
    """The studies of the sliced run groups and their parents, as the build keeps them."""
    named = run_groups["study_accession"].drop_nulls().unique().to_list()
    rows = conn.execute(
        f"SELECT {', '.join(STUDY_COLUMNS)} FROM study WHERE study_accession = ANY(%s) "
        "OR study_accession IN (SELECT unnest(parents) FROM study WHERE study_accession = ANY(%s))",
        (named, named),
    ).fetchall()
    studies = pl.DataFrame(
        rows,
        schema={"study_accession": pl.Utf8, "title": pl.Utf8, "parents": pl.List(pl.Utf8)},
        orient="row",
    )
    return _studies_to_keep(studies, run_groups).sort("study_accession")


def fetch_merged(conn: psycopg.Connection, taxids: list[int]) -> list[tuple]:
    """A few merged taxids of the slice's taxa."""
    return conn.execute(
        "SELECT taxid, merged_into FROM taxon_merged WHERE merged_into = ANY(%s) "
        "ORDER BY merged_into, taxid LIMIT %s",
        (taxids, MERGED_CAP),
    ).fetchall()


def build_clade_stats(
    taxon: pl.DataFrame, assemblies: list[tuple], annotations: list[tuple]
) -> pl.DataFrame:
    """Recompute ``clade_stats`` from the slice's own records, as the build does."""
    def frame(rows: list[tuple], columns: tuple[str, ...], keep: dict[str, pl.DataType]):
        index = {c: i for i, c in enumerate(columns)}
        return pl.DataFrame(
            {c: [r[index[c]] for r in rows] for c in keep}, schema=keep
        )

    records = {
        "assembly": frame(
            assemblies, ASSEMBLY_COLUMNS,
            {"taxid": pl.Int64, "total_sequence_length": pl.Int64, "contig_n50": pl.Int64},
        ),
        "annotation": frame(
            annotations, ANNOTATION_COLUMNS,
            {"taxid": pl.Int64, "protein_coding_count": pl.Int64, "busco_complete": pl.Float64},
        ),
    }
    return stats_from_records(
        taxon.select("taxid", "path"), records, root_taxid=EUKARYOTA_TAXID
    )


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
        run_groups = fetch_run_groups(conn, slice_taxids)
        studies = fetch_studies(conn, run_groups)
        merged = fetch_merged(conn, slice_taxids)
        clade = build_clade_features(taxon, assemblies, annotations, run_groups)
        stats = build_clade_stats(taxon, assemblies, annotations)
        assemblies = link_assemblies(taxon, assemblies, annotations)

    n_species = taxon.filter(pl.col("rank") == "species").height
    counts = (
        f"-- taxon={taxon.height} clade_features={clade.height} "
        f"clade_stats={stats.height} assembly={len(assemblies)} annotation={len(annotations)} "
        f"rna_seq_runs={run_groups.height} study={studies.height} taxon_merged={len(merged)}"
    )
    lines: list[str] = [
        "-- EukaHub CI test seed — GENERATED by scripts/generate_ci_seed.py.",
        "-- A compact, self-consistent slice of the serving DB for the DB-backed",
        "-- API tests. Do not edit by hand; re-run the generator instead.",
        counts,
        "",
        "BEGIN;",
        (
            "TRUNCATE study, rna_seq_runs, annotation, assembly, clade_stats, clade_features, "
            "taxon_merged, taxon RESTART IDENTITY CASCADE;"
        ),
        "",
    ]

    clade_cols = ("taxid", "n_rows", *clade_feature_columns())
    emit_insert(lines, "taxon", TAXON_COLUMNS, taxon.rows())
    lines.append("")
    emit_insert(lines, "taxon_merged", ("taxid", "merged_into"), merged)
    lines.append("")
    emit_insert(lines, "clade_features", clade_cols,
                clade.select(list(clade_cols)).rows())
    lines.append("")
    emit_insert(lines, "clade_stats", ("taxid", *QUALITY_KEYS), stats.rows())
    lines.append("")
    emit_insert(lines, "assembly", ASSEMBLY_TABLE_COLUMNS, assemblies)
    lines.append("")
    emit_insert(lines, "annotation", ANNOTATION_COLUMNS, annotations)
    lines.append("")
    emit_insert(lines, "rna_seq_runs", RUN_GROUP_COLUMNS, run_groups.rows())
    lines.append("")
    emit_insert(lines, "study", STUDY_COLUMNS, studies.rows())
    lines.append("")
    lines.append("COMMIT;")
    lines.append("")

    out_path.write_text("\n".join(lines))
    print(
        f"Wrote {out_path} — taxon={taxon.height} (species={n_species}) "
        f"clade_features={clade.height} clade_stats={stats.height} "
        f"assembly={len(assemblies)} annotation={len(annotations)} "
        f"rna_seq_runs={run_groups.height} study={studies.height} taxon_merged={len(merged)}"
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
