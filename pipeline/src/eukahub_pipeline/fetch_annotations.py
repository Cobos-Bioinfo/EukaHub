"""Fetch per-annotation records from Annotrieve (genome.crg.es/annotrieve).

Replaces Euka-Survey's ``get_annotations``, which hit the
``/annotations/frequencies/taxid`` endpoint and kept only per-taxon counts.
Annotrieve already computes the rich annotation metadata we want — source DB,
provider, GFF url, gene counts, and BUSCO — so we download its TSV report of
every annotation in one request and keep it per-record for the ``annotation``
table. The per-taxon annotation *count* the roll-up needs is derived later by
grouping these rows (Stage B).

Everything Annotrieve serves is kept, including community-contributed
annotations such as TOGA2 projections (docs/decisions.md). The authoritative
assembly count still comes from ``fetch_assemblies`` (NCBI datasets).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from eukahub_pipeline.sources import ANNOTRIEVE, Source

log = logging.getLogger("eukahub.fetch_annotations")

# Column set of the `annotation` table (infra/postgres/init/001_schema.sql).
ANNOTATION_COLUMNS: tuple[str, ...] = (
    "annotation_id",
    "assembly_accession",
    "taxid",
    "source_database",
    "provider",
    "release_date",
    "gff_url",
    "gene_count",
    "protein_coding_count",
    "busco_complete",
    "busco_single_copy",
    "busco_duplicated",
    "busco_lineage",
)

# Optional report columns requested on top of the defaults (id, accession,
# taxid, database, provider, source_url, ...).
REPORT_FIELDS: tuple[str, ...] = (
    "release_date",
    "root_type_counts",
    "coding_gene_count",
    "busco_complete",
    "busco_single_copy",
    "busco_duplicated",
    "busco_lineage",
)
_REQUIRED_HEADER = {
    "annotation_id", "assembly_accession", "taxid", "database", "provider", "source_url",
    *REPORT_FIELDS,
}


def _to_int(value: object) -> int | None:
    """Cast to int (the report is text). None on failure."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_report_row(row: dict[str, str]) -> dict | None:
    """Normalize one row of the report into an ``annotation`` row.

    Returns ``None`` when the row lacks an id or a taxid. Empty cells become
    ``None``; the gene count comes from the ``root_type_counts`` JSON object.
    Pure and network-free, so it is the unit the tests exercise.
    """
    cell = {key: value or None for key, value in row.items()}
    ann_id = cell.get("annotation_id")
    taxid = _to_int(cell.get("taxid"))
    if not ann_id or taxid is None:
        return None

    try:
        root_counts = json.loads(cell.get("root_type_counts") or "{}")
    except json.JSONDecodeError:
        root_counts = None
    if not isinstance(root_counts, dict):
        root_counts = {}
    release = cell.get("release_date")  # ISO datetime or None
    return {
        "annotation_id": ann_id,
        "assembly_accession": cell.get("assembly_accession"),
        "taxid": taxid,
        "source_database": cell.get("database"),
        "provider": cell.get("provider"),
        "release_date": release[:10] if release else None,
        "gff_url": cell.get("source_url"),
        "gene_count": _to_int(root_counts.get("gene")),
        "protein_coding_count": _to_int(cell.get("coding_gene_count")),
        "busco_complete": _to_float(cell.get("busco_complete")),
        "busco_single_copy": _to_float(cell.get("busco_single_copy")),
        "busco_duplicated": _to_float(cell.get("busco_duplicated")),
        "busco_lineage": cell.get("busco_lineage"),
    }


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def _get_report(source: Source) -> str:
    """The TSV report of every annotation, retried with backoff on transient errors."""
    resp = requests.get(
        f"{source.url}/annotations/report",
        params={"selected_fields": ",".join(REPORT_FIELDS)},
        timeout=source.timeout,
    )
    resp.raise_for_status()
    return resp.text


def fetch_annotations(source: Source = ANNOTRIEVE) -> Iterator[dict]:
    """Download Annotrieve's annotation report and yield normalized rows.

    Raises ``RuntimeError`` if the report lacks a column we need or has no rows,
    so a changed or truncated response fails the build instead of shipping a
    dataset without annotations.
    """
    lines = _get_report(source).splitlines()
    header = lines[0].split("\t") if lines else []
    missing = _REQUIRED_HEADER - set(header)
    if missing:
        raise RuntimeError(f"Annotrieve report is missing columns: {sorted(missing)}")
    if len(lines) < 2:
        raise RuntimeError("Annotrieve report has no rows")
    log.info("Annotrieve report has %d annotations", len(lines) - 1)

    n_kept = 0
    for line in lines[1:]:
        row = parse_report_row(dict(zip(header, line.split("\t"))))
        if row is not None:
            n_kept += 1
            yield row
    log.info("Fetched %d annotation rows", n_kept)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    rows = list(fetch_annotations())
    log.info("Fetched %d annotations", len(rows))
    for row in rows[:5]:
        log.info("%s", row)
