"""Fetch per-taxon RNA-Seq run counts from EBI ENA.

Ports Euka-Survey's ``get_reads``: ENA portal queries for eukaryote RNA-Seq
runs, counting runs per taxon and splitting long-read (Oxford Nanopore / PacBio
SMRT) from the rest. Reads stay **aggregated** per taxon — ENA has ~8M runs, too
many to serve per-record (docs/decisions.md) — and are **run counts only**,
no ``base_count`` (same decision), so they stay parallel to the other three
resources.

Short-read and long-read runs are two queries asking only for ``tax_id`` (the
platform is implied), read as TSV line by line, so memory stays flat however
many runs ENA has. ENA sometimes ends a large response early, in any format, so
each query is checked against ENA's own count and retried when short.
"""

from __future__ import annotations

import logging
from collections import Counter

import requests
from eukahub_core.taxonomy import EUKARYOTA_TAXID
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from eukahub_pipeline.sources import ENA, Source

log = logging.getLogger("eukahub.fetch_reads")

_RNA_SEQ = (
    f"tax_tree({EUKARYOTA_TAXID}) AND "
    '(library_source="transcriptomic" OR library_strategy="rna-seq")'
)
_LONG_READ_PLATFORMS = ("OXFORD_NANOPORE", "PACBIO_SMRT")
_LONG_QUERY = f"{_RNA_SEQ} AND (" + " OR ".join(
    f'instrument_platform="{p}"' for p in _LONG_READ_PLATFORMS
) + ")"
_SHORT_QUERY = f"{_RNA_SEQ} AND (" + " AND ".join(
    f'instrument_platform!="{p}"' for p in _LONG_READ_PLATFORMS
) + ")"
# A download must hold at least this share of the runs ENA's count endpoint
# reports (a little slack for runs withdrawn between the two requests).
_MIN_COMPLETE = 0.99

# Per-taxon aggregate columns feeding the roll-up leaf features.
READS_COLUMNS: tuple[str, ...] = ("taxid", "short", "long")


def _post(
    source: Source, endpoint: str, query: str, *, stream: bool = False, **fields: str | int
) -> requests.Response:
    """POST a read-run query to an ENA portal endpoint."""
    resp = requests.post(
        f"{source.url}/{endpoint}",
        data={"result": "read_run", "query": query, **fields},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=source.timeout,
        stream=stream,
    )
    resp.raise_for_status()
    return resp


def _expected_runs(source: Source, query: str) -> int:
    """How many runs match ``query``, from ENA's count endpoint ("count\\n<n>")."""
    return int(_post(source, "count", query).text.split()[-1])


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _runs_per_taxon(source: Source, query: str) -> Counter[int]:
    """Runs per taxon matching ``query``, counted line by line from ENA's TSV
    stream and retried with backoff until the download is complete."""
    expected = _expected_runs(source, query)
    counts: Counter[int] = Counter()
    runs = 0
    with _post(source, "search", query, stream=True, fields="tax_id", format="tsv", limit=0) as resp:
        lines = resp.iter_lines(chunk_size=1 << 20)
        header = next(lines, b"").decode("utf-8").split("\t")
        if "tax_id" not in header:
            raise RuntimeError(f"unexpected ENA header: {header}")
        column = header.index("tax_id")
        for line in lines:
            try:
                counts[int(line.split(b"\t")[column])] += 1
            except (IndexError, ValueError):
                continue
            runs += 1
    if not runs or runs < expected * _MIN_COMPLETE:
        raise RuntimeError(f"ENA returned {runs} of {expected} runs")
    return counts


def fetch_reads(source: Source = ENA) -> list[dict]:
    """Return per-taxon RNA-Seq run counts as rows of ``{taxid, short, long}``.

    ``short`` = runs on any non-long-read platform; ``long`` = Oxford Nanopore /
    PacBio SMRT runs (``rna`` = short+long and ``lng`` = long are derived in the
    roll-up, matching the existing metrics).
    """
    short = _runs_per_taxon(source, _SHORT_QUERY)
    long = _runs_per_taxon(source, _LONG_QUERY)
    taxids = short.keys() | long.keys()
    log.info(
        "ENA: %d short-read and %d long-read runs across %d taxa",
        short.total(),
        long.total(),
        len(taxids),
    )
    return [{"taxid": t, "short": short[t], "long": long[t]} for t in taxids]


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
