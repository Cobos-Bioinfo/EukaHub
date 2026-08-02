"""Fetch per-assembly records from the NCBI ``datasets`` CLI.

Replaces Euka-Survey's ``get_assemblies``, which ran the same command but kept
only ``organism.tax_id`` and incremented a per-taxon counter — discarding all
the metadata the summary returns. Here we normalize each record into an
``assembly`` row (level, N50s, genome size, GC, refseq_category, release date,
submitter, source DB, bioprojects, a deep link). The per-taxon assembly *count*
the roll-up needs is derived later by grouping these rows on ``taxid`` (Stage B).

Covers **all** assemblies (annotated or not); Annotrieve supplies the annotation
richness on the annotated subset separately (``fetch_annotations``).
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterator

log = logging.getLogger("eukahub.fetch_assemblies")

EUKARYOTE_TXID = 2759

# Column set of the `assembly` table (infra/postgres/init/001_schema.sql), in
# order — the per-record dicts yielded here use exactly these keys.
ASSEMBLY_COLUMNS: tuple[str, ...] = (
    "assembly_accession",
    "taxid",
    "assembly_level",
    "contig_n50",
    "scaffold_n50",
    "total_sequence_length",
    "gc_percent",
    "refseq_category",
    "release_date",
    "submitter",
    "source_database",
    "bioprojects",
    "download_url",
)


class DatasetsCLIError(RuntimeError):
    """Raised when the NCBI datasets CLI is missing or exits non-zero."""


def _to_int(value: object) -> int | None:
    """Cast to int, tolerating the numeric *strings* datasets uses for big
    fields (e.g. ``total_sequence_length: "143706478"``). None on failure."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_source_db(value: object) -> str | None:
    """``SOURCE_DATABASE_REFSEQ`` -> ``RefSeq``, ``..._GENBANK`` -> ``GenBank``."""
    if not value:
        return None
    tail = str(value).rsplit("_", 1)[-1].upper()
    return {"REFSEQ": "RefSeq", "GENBANK": "GenBank"}.get(tail, str(value))


def _bioprojects(assembly_info: dict) -> list[str]:
    """Distinct BioProject accessions from the top-level field + the lineage."""
    accs: set[str] = set()
    top = assembly_info.get("bioproject_accession")
    if top:
        accs.add(top)
    for node in assembly_info.get("bioproject_lineage") or []:
        for bp in node.get("bioprojects") or []:
            acc = bp.get("accession")
            if acc:
                accs.add(acc)
    return sorted(accs)


def parse_assembly_record(record: dict) -> dict | None:
    """Normalize one ``datasets`` JSON-lines record into an ``assembly`` row.

    Returns ``None`` when the record lacks an accession or a taxid (unusable).
    Pure and network-free, so it is the unit the tests exercise.
    """
    accession = record.get("accession")
    organism = record.get("organism") or {}
    taxid = organism.get("tax_id")
    if not accession or taxid is None:
        return None

    info = record.get("assembly_info") or {}
    stats = record.get("assembly_stats") or {}
    release = info.get("release_date")  # 'YYYY-MM-DD' or None
    return {
        "assembly_accession": accession,
        "taxid": _to_int(taxid),
        "assembly_level": info.get("assembly_level"),
        "contig_n50": _to_int(stats.get("contig_n50")),
        "scaffold_n50": _to_int(stats.get("scaffold_n50")),
        "total_sequence_length": _to_int(stats.get("total_sequence_length")),
        "gc_percent": stats.get("gc_percent"),
        "refseq_category": info.get("refseq_category"),
        "release_date": release[:10] if release else None,
        "submitter": info.get("submitter"),
        "source_database": _normalize_source_db(record.get("source_database")),
        "bioprojects": _bioprojects(info),
        "download_url": f"https://www.ncbi.nlm.nih.gov/datasets/genome/{accession}/",
    }


def fetch_assemblies(
    txid: int = EUKARYOTE_TXID, *, datasets_bin: str = "datasets"
) -> Iterator[dict]:
    """Stream normalized ``assembly`` rows for ``txid`` and its descendants.

    Runs ``datasets summary genome taxon <txid> --as-json-lines`` and parses
    each line. Raises :class:`DatasetsCLIError` if the CLI is missing or fails.
    """
    try:
        proc = subprocess.Popen(
            [datasets_bin, "summary", "genome", "taxon", str(txid), "--as-json-lines"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise DatasetsCLIError(
            "NCBI datasets CLI not found. Install from "
            "https://www.ncbi.nlm.nih.gov/datasets/docs/v2/command-line-tools/"
        ) from e

    n_seen = n_kept = 0
    for raw in proc.stdout:  # type: ignore[union-attr]
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("Skipping malformed assembly record: %s", e)
            continue
        n_seen += 1
        row = parse_assembly_record(record)
        if row is not None:
            n_kept += 1
            yield row

    proc.wait()
    if proc.returncode != 0:
        stderr = (proc.stderr.read() if proc.stderr else "").strip()
        raise DatasetsCLIError(f"datasets exited {proc.returncode}: {stderr}")
    log.info("Parsed %d assembly records (%d usable) under taxon %d", n_seen, n_kept, txid)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    import sys

    root = int(sys.argv[1]) if len(sys.argv) > 1 else EUKARYOTE_TXID
    rows = list(fetch_assemblies(root))
    log.info("Fetched %d assemblies under taxon %d", len(rows), root)
    for row in rows[:5]:
        log.info("%s", row)
