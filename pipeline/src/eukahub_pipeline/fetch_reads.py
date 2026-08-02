"""Fetch per-taxon RNA-Seq run counts from EBI ENA.

Ports Euka-Survey's ``get_reads``: one ENA portal query for eukaryote RNA-Seq
runs, counting runs per taxon and splitting long-read (Oxford Nanopore / PacBio
SMRT) from the rest. Reads stay **aggregated** per taxon — ENA has ~8M runs, too
many to serve per-record (DECISIONS.md 2026-08-02) — and are **run counts only**,
no ``base_count`` (same decision), so they stay parallel to the other three
resources.

Note on format (kept from Euka-Survey): ``format=tsv`` streaming returned a
fraction of the rows (an undocumented cap / severed stream), so we use
``format=json`` and materialize the payload — a few hundred MB for the current
~8M-row response, acceptable for an offline build.
"""

from __future__ import annotations

import logging

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("eukahub.fetch_reads")

ENA_BASE = "https://www.ebi.ac.uk/ena/portal/api/search"
EUKARYOTE_TXID = 2759

_LONG_READ_PLATFORMS = {"OXFORD_NANOPORE", "PACBIO_SMRT"}

# Per-taxon aggregate columns feeding the roll-up leaf features.
READS_COLUMNS: tuple[str, ...] = ("taxid", "short", "long")


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=60))
def _query_ena() -> list[dict]:
    """POST the ENA portal query and return the full JSON payload (list of
    ``{tax_id, instrument_platform}`` rows). Retried with backoff."""
    payload = {
        "result": "read_run",
        "query": (
            f"tax_tree({EUKARYOTE_TXID}) AND "
            f'(library_source="transcriptomic" OR library_strategy="rna-seq")'
        ),
        "fields": "tax_id,instrument_platform",
        "format": "json",
        "limit": 0,
    }
    resp = requests.post(
        ENA_BASE,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        # Empty is a hard failure — the Eukaryota RNA-Seq query always has rows.
        raise RuntimeError("empty ENA response")
    return data


def fetch_reads() -> list[dict]:
    """Return per-taxon RNA-Seq run counts as rows of ``{taxid, short, long}``.

    ``short`` = runs on any non-long-read platform; ``long`` = Oxford Nanopore /
    PacBio SMRT runs (``rna`` = short+long and ``lng`` = long are derived in the
    roll-up, matching the existing metrics).
    """
    data = _query_ena()
    counts: dict[int, list[int]] = {}  # taxid -> [short, long]
    for record in data:
        try:
            taxid = int(record.get("tax_id"))
        except (TypeError, ValueError):
            continue
        entry = counts.setdefault(taxid, [0, 0])
        if record.get("instrument_platform", "") in _LONG_READ_PLATFORMS:
            entry[1] += 1
        else:
            entry[0] += 1

    rows = [
        {"taxid": taxid, "short": short, "long": long}
        for taxid, (short, long) in counts.items()
    ]
    log.info("ENA: %d runs across %d taxa", len(data), len(rows))
    return rows


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    result = fetch_reads()
    log.info("Fetched read counts for %d taxa", len(result))
    for row in result[:5]:
        log.info("%s", row)
