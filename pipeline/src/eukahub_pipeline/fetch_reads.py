"""Fetch per-taxon RNA-Seq run counts from EBI ENA.

Ports Euka-Survey's ``get_reads``: one ENA portal query for eukaryote RNA-Seq
runs, counting runs per taxon and splitting long-read (Oxford Nanopore / PacBio
SMRT) from the rest. Reads stay **aggregated** per taxon — ENA has ~8M runs, too
many to serve per-record (docs/decisions.md) — and are **run counts only**,
no ``base_count`` (same decision), so they stay parallel to the other three
resources.

Note on format (kept from Euka-Survey): ``format=tsv`` streaming returned a
fraction of the rows (an undocumented cap / severed stream), so we use
``format=json``. The array is parsed as it arrives and runs are counted on the
fly, so memory stays flat however many runs ENA has.
"""

from __future__ import annotations

import codecs
import json
import logging
import re
from collections.abc import Iterable, Iterator
from typing import Any

import requests
from eukahub_core.taxonomy import EUKARYOTA_TAXID
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from eukahub_pipeline.sources import ENA, Source

log = logging.getLogger("eukahub.fetch_reads")

_QUERY = (
    f"tax_tree({EUKARYOTA_TAXID}) AND "
    '(library_source="transcriptomic" OR library_strategy="rna-seq")'
)
# ENA sometimes ends a large response early with a shorter but valid payload. A
# download must hold at least this share of the runs ENA's count endpoint reports
# (a little slack for runs withdrawn between the two requests).
_MIN_COMPLETE = 0.99

_LONG_READ_PLATFORMS = {"OXFORD_NANOPORE", "PACBIO_SMRT"}

# Per-taxon aggregate columns feeding the roll-up leaf features.
READS_COLUMNS: tuple[str, ...] = ("taxid", "short", "long")


# Whitespace and punctuation between the elements of a JSON array.
_BETWEEN_ELEMENTS = re.compile(r"[\s,\[\]]*")
# A larger unparsed remainder means a malformed stream, not one run record.
_MAX_ELEMENT_CHARS = 1 << 20


def _post(
    source: Source, endpoint: str, *, stream: bool = False, **fields: str | int
) -> requests.Response:
    """POST the RNA-Seq read-run query to an ENA portal endpoint."""
    resp = requests.post(
        f"{source.url}/{endpoint}",
        data={"result": "read_run", "query": _QUERY, **fields},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=source.timeout,
        stream=stream,
    )
    resp.raise_for_status()
    return resp


def iter_json_array(chunks: Iterable[bytes]) -> Iterator[Any]:
    """The elements of a JSON array of objects, parsed as its UTF-8 bytes arrive.
    Raises ``ValueError`` if the array is malformed or cut short."""
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    buf, closed, done = "", False, False
    chunks = iter(chunks)
    while not done:
        chunk = next(chunks, None)
        done = chunk is None
        buf += utf8.decode(b"" if done else chunk, final=done)
        pos = 0
        while True:
            gap = _BETWEEN_ELEMENTS.match(buf, pos)
            closed = closed or "]" in gap.group()
            pos = gap.end()
            if pos == len(buf):
                break
            try:
                element, pos = decoder.raw_decode(buf, pos)
            except json.JSONDecodeError:
                if done:
                    raise ValueError("malformed JSON array") from None
                break  # the element continues in the next chunk
            yield element
        buf = buf[pos:]
        if len(buf) > _MAX_ELEMENT_CHARS:
            raise ValueError("malformed JSON array")
    if not closed:
        raise ValueError("the JSON array was cut short")


def _expected_runs(source: Source) -> int:
    """How many runs match the query, from ENA's count endpoint ("count\\n<n>")."""
    return int(_post(source, "count").text.split()[-1])


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _count_runs(source: Source) -> dict[int, list[int]]:
    """Runs per taxon as ``{taxid: [short, long]}``, counted while ENA streams
    them, retrying with backoff until the download is complete."""
    expected = _expected_runs(source)
    counts: dict[int, list[int]] = {}
    runs = 0
    with _post(
        source, "search", stream=True, fields="tax_id,instrument_platform", format="json", limit=0
    ) as resp:
        for record in iter_json_array(resp.iter_content(chunk_size=1 << 20)):
            runs += 1
            try:
                taxid = int(record.get("tax_id"))
            except (TypeError, ValueError):
                continue
            entry = counts.setdefault(taxid, [0, 0])
            entry[1 if record.get("instrument_platform", "") in _LONG_READ_PLATFORMS else 0] += 1
    if not runs or runs < expected * _MIN_COMPLETE:
        raise RuntimeError(f"ENA returned {runs} of {expected} runs")
    log.info("ENA: %d runs across %d taxa", runs, len(counts))
    return counts


def fetch_reads(source: Source = ENA) -> list[dict]:
    """Return per-taxon RNA-Seq run counts as rows of ``{taxid, short, long}``.

    ``short`` = runs on any non-long-read platform; ``long`` = Oxford Nanopore /
    PacBio SMRT runs (``rna`` = short+long and ``lng`` = long are derived in the
    roll-up, matching the existing metrics).
    """
    return [
        {"taxid": taxid, "short": short, "long": long}
        for taxid, (short, long) in _count_runs(source).items()
    ]


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
