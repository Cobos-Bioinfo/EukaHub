"""Fetch per-annotation records from Annotrieve (genome.crg.es/annotrieve).

Replaces Euka-Survey's ``get_annotations``, which hit the
``/annotations/frequencies/taxid`` endpoint and kept only per-taxon counts.
Annotrieve already computes the rich annotation metadata we want — source DB,
provider, GFF url, gene counts, and BUSCO — so we page through ``/annotations``
and keep it per-record for the ``annotation`` table. The per-taxon annotation
*count* the roll-up needs is derived later by grouping these rows (Stage B).

Annotrieve is the *annotated subset* (~17k assemblies), so these rows light up
the reference-quality core of the tree; the authoritative assembly count still
comes from ``fetch_assemblies`` (NCBI datasets). See DECISIONS.md (2026-08-02).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("eukahub.fetch_annotations")

ANNOTRIEVE_BASE = "https://genome.crg.es/annotrieve/api/v0"

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


def _to_int(value: object) -> int | None:
    """Cast to int (Annotrieve sends ``taxid`` as a string). None on failure."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_annotation_record(record: dict) -> dict | None:
    """Normalize one Annotrieve annotation into an ``annotation`` row.

    Returns ``None`` when the record lacks an id or a taxid. Pulls gene counts
    from ``features_summary.root_type_counts.gene`` and the protein-coding total
    from ``features_statistics.gene_category_stats.coding.total_count``; BUSCO
    and ``features_statistics`` may be absent, hence the defensive ``.get``s.
    Pure and network-free, so it is the unit the tests exercise.
    """
    ann_id = record.get("annotation_id")
    taxid = _to_int(record.get("taxid"))
    if not ann_id or taxid is None:
        return None

    source = record.get("source_file_info") or {}
    summary = record.get("features_summary") or {}
    stats = record.get("features_statistics") or {}
    busco = record.get("busco") or {}

    root_counts = summary.get("root_type_counts") or {}
    coding = (stats.get("gene_category_stats") or {}).get("coding") or {}
    release = source.get("release_date")  # ISO datetime string or None
    return {
        "annotation_id": ann_id,
        "assembly_accession": record.get("assembly_accession"),
        "taxid": taxid,
        "source_database": source.get("database"),
        "provider": source.get("provider"),
        "release_date": release[:10] if release else None,
        "gff_url": source.get("url_path"),
        "gene_count": _to_int(root_counts.get("gene")),
        "protein_coding_count": _to_int(coding.get("total_count")),
        "busco_complete": busco.get("complete"),
        "busco_single_copy": busco.get("single_copy"),
        "busco_duplicated": busco.get("duplicated"),
        "busco_lineage": busco.get("busco_lineage"),
    }


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def _get_page(session: requests.Session, base: str, offset: int, limit: int) -> dict:
    """One page of ``/annotations`` — retried with backoff on transient errors."""
    resp = session.get(
        f"{base}/annotations",
        params={"offset": offset, "limit": limit},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_annotations(
    *, base: str = ANNOTRIEVE_BASE, page_size: int = 500
) -> Iterator[dict]:
    """Page through Annotrieve ``/annotations``, yielding normalized rows.

    The response envelope is ``{total, offset, limit, results}``; we advance
    ``offset`` by the page length until it reaches ``total`` (or a page comes
    back empty).
    """
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    offset = 0
    total: int | None = None
    n_kept = 0
    while True:
        page = _get_page(session, base, offset, page_size)
        results = page.get("results") or []
        if total is None:
            total = page.get("total")
            log.info("Annotrieve reports %s annotations", total)
        if not results:
            break
        for record in results:
            row = parse_annotation_record(record)
            if row is not None:
                n_kept += 1
                yield row
        offset += len(results)
        if total is not None and offset >= total:
            break
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
