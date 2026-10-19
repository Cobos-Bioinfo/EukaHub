"""Fetch eukaryote RNA-Seq runs and their studies from EBI ENA.

Ports Euka-Survey's ``get_reads``: ENA portal queries for eukaryote RNA-Seq
runs, splitting long-read (Oxford Nanopore / PacBio SMRT) from short-read runs.
ENA has about 8.5 million such runs, too many to serve one by one
(docs/decisions.md), so they are counted per taxon, study, submitting centre and
year of first release, with their bases and reads summed: enough for the clade
counts, finding runs by project, centres and growth over time.

Short-read and long-read runs are two queries (the platform is implied), read as
TSV line by line, so memory follows the number of groups, not of runs. ENA
sometimes ends a large response early, in any format, so each query is checked
against ENA's own count and retried when short. The studies are a third query.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

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
_RUN_FIELDS = ("tax_id", "study_accession", "center_name", "first_public", "base_count", "read_count")
_STUDY_QUERY = f"tax_tree({EUKARYOTA_TAXID})"
_STUDY_FIELDS = ("study_accession", "parent_study_accession", "study_title")
# A download must hold at least this share of the rows ENA's count endpoint
# reports (a little slack for rows withdrawn between the two requests).
_MIN_COMPLETE = 0.99

# One row per group of runs, the columns of the `rna_seq_runs` table.
RUN_GROUP_COLUMNS: tuple[str, ...] = (
    "taxid",
    "study_accession",
    "long_read",
    "center_name",
    "first_public_year",
    "runs",
    "bases",
    "reads",
)
STUDY_COLUMNS: tuple[str, ...] = ("study_accession", "title", "parents")

# (taxid, study_accession, center_name, first_public_year) -> [runs, bases, reads];
# bases and reads stay None until a run reports them.
_Groups = dict[tuple[int, str | None, str | None, int | None], list[int | None]]


def _post(
    source: Source, endpoint: str, result: str, query: str, *, stream: bool = False,
    **fields: str | int,
) -> requests.Response:
    """POST a query to an ENA portal endpoint."""
    resp = requests.post(
        f"{source.url}/{endpoint}",
        data={"result": result, "query": query, **fields},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=source.timeout,
        stream=stream,
    )
    resp.raise_for_status()
    return resp


def _expected(source: Source, result: str, query: str) -> int:
    """How many rows match ``query``, from ENA's count endpoint ("count\\n<n>")."""
    return int(_post(source, "count", result, query).text.split()[-1])


def _rows(source: Source, result: str, query: str, fields: tuple[str, ...]) -> Iterator[list[str]]:
    """The rows of a TSV search as lists of ``fields`` values, streamed, checked
    against ENA's count: a short download raises ``RuntimeError`` after its last
    row. Rows with a stray tab or line break in a value are skipped."""
    expected = _expected(source, result, query)
    n = 0
    with _post(
        source, "search", result, query, stream=True, fields=",".join(fields), format="tsv",
        limit=0,
    ) as resp:
        lines = resp.iter_lines(chunk_size=1 << 20)
        header = next(lines, b"").decode("utf-8").split("\t")
        if not set(fields) <= set(header):
            raise RuntimeError(f"unexpected ENA header: {header}")
        columns = [header.index(f) for f in fields]
        for line in lines:
            cells = line.decode("utf-8", errors="replace").split("\t")
            if len(cells) != len(header):
                continue
            n += 1
            yield [cells[c] for c in columns]
    if not n or n < expected * _MIN_COMPLETE:
        raise RuntimeError(f"ENA returned {n} of {expected} {result} rows")


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _run_groups(source: Source, query: str) -> _Groups:
    """The runs matching ``query`` counted per (taxid, study, centre, year), with
    their bases and reads summed; retried with backoff until the download is
    complete."""
    groups: _Groups = {}
    for tax_id, study, center, first_public, base_count, read_count in _rows(
        source, "read_run", query, _RUN_FIELDS
    ):
        taxid = _int(tax_id)
        if taxid is None:
            continue
        key = (taxid, study or None, center or None, _int(first_public[:4]))
        group = groups.get(key)
        if group is None:
            group = groups[key] = [0, None, None]
        group[0] += 1
        for i, value in ((1, _int(base_count)), (2, _int(read_count))):
            if value is not None:
                group[i] = (group[i] or 0) + value
    return groups


def fetch_reads(source: Source = ENA) -> Iterator[dict]:
    """Yield the eukaryote RNA-Seq runs as groups, one row per (taxid, study,
    short or long read, centre, year of first release): ``RUN_GROUP_COLUMNS``."""
    for long_read, query in ((False, _SHORT_QUERY), (True, _LONG_QUERY)):
        groups = _run_groups(source, query)
        log.info(
            "ENA: %d %s-read runs in %d groups",
            sum(g[0] for g in groups.values()), "long" if long_read else "short", len(groups),
        )
        for (taxid, study, center, year), (runs, bases, reads) in groups.items():
            yield {
                "taxid": taxid,
                "study_accession": study,
                "long_read": long_read,
                "center_name": center,
                "first_public_year": year,
                "runs": runs,
                "bases": bases,
                "reads": reads,
            }


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _studies(source: Source) -> list[dict]:
    """Every eukaryote study ENA has, retried with backoff until complete."""
    return [
        {"study_accession": acc, "title": title or None, "parents": [p for p in parents.split(";") if p]}
        for acc, parents, title in _rows(source, "study", _STUDY_QUERY, _STUDY_FIELDS)
        if acc
    ]


def fetch_studies(source: Source = ENA) -> Iterator[dict]:
    """Yield every eukaryote study (BioProject) in ENA with its title and parent
    projects: ``STUDY_COLUMNS``. The build keeps those with RNA-Seq runs and their
    parents."""
    studies = _studies(source)
    log.info("ENA: %d studies", len(studies))
    yield from studies


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for row in fetch_reads():
        log.info("%s", row)
        break
