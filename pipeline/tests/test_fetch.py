"""Network-free tests for the fetch parsers.

The parsers (``parse_assembly_record`` / ``parse_report_row``) are pure,
so we exercise them on captured real-shaped records — no datasets CLI, no
Annotrieve. The ENA fetch runs against a stubbed ``_post`` and the Annotrieve
fetch against stubbed report lines. The live fetch wrappers are covered by manual
smoke runs, not CI.
"""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Iterator
from typing import Self

import polars as pl
import pytest
from eukahub_pipeline import fetch_annotations as fa
from eukahub_pipeline import fetch_reads as fr
from eukahub_pipeline.fetch_annotations import (
    ANNOTATION_COLUMNS,
    parse_report_row,
)
from eukahub_pipeline.fetch_assemblies import (
    ASSEMBLY_COLUMNS,
    drop_duplicate_assemblies,
    fetch_assemblies,
    parse_assembly_record,
)
from eukahub_pipeline.sources import ENA
from tenacity import stop_after_attempt, wait_none

# A trimmed but real-shaped `datasets summary genome ... --as-json-lines` record.
ASSEMBLY_RECORD = {
    "accession": "GCF_000001215.4",
    "organism": {"organism_name": "Drosophila melanogaster", "tax_id": 7227},
    "source_database": "SOURCE_DATABASE_REFSEQ",
    "assembly_info": {
        "assembly_level": "Chromosome",
        "refseq_category": "reference genome",
        "release_date": "2014-08-01",
        "submitter": "The FlyBase Consortium",
        "bioproject_accession": "PRJNA13812",
        "bioproject_lineage": [
            {"bioprojects": [{"accession": "PRJNA13812"}, {"accession": "PRJNA13"}]}
        ],
    },
    "assembly_stats": {
        "total_sequence_length": "143706478",  # datasets sends this as a string
        "contig_n50": 21485538,
        "scaffold_n50": 25286936,
        "gc_percent": 42,
    },
}

# A trimmed but real-shaped Annotrieve /annotations record.
# One row of Annotrieve's /annotations/report with the REPORT_FIELDS columns.
REPORT_HEADER = (
    "annotation_id\tassembly_accession\tassembly_name\torganism_name\ttaxid\tdatabase\t"
    "provider\tsource_url\tbgzip_path\tcsi_path\trelease_date\tbusco_lineage\t"
    "busco_complete\tbusco_single_copy\tbusco_duplicated\troot_type_counts\t"
    "coding_gene_count"
)
REPORT_LINE = (
    "f628158077010762f66c13935b5630a3\tGCA_001624475.1\tCBA_J_v1\tMus musculus\t10090\t"
    "Ensembl\tcommunity\thttps://ftp.ebi.ac.uk/pub/.../genes.gff3.gz\t/10090/a.gff.gz\t"
    "/10090/a.gff.gz.csi\t2018-01-01T00:00:00\teukaryota_odb12\t99.2\t97.7\t1.6\t"
    '{"chromosome":20,"gene":22685,"pseudogene":6269}\t20589'
)
ANNOTATION_ROW = dict(zip(REPORT_HEADER.split("\t"), REPORT_LINE.split("\t")))


def test_stopping_the_assembly_fetch_early_stops_the_cli(tmp_path):
    """A caller that reads only a few rows must not leave ``datasets`` running."""
    record = json.dumps(ASSEMBLY_RECORD).replace("'", "")
    fake = tmp_path / "datasets"
    fake.write_text(f"#!/bin/sh\necho $$ > {tmp_path}/pid\nwhile true; do echo '{record}'; done\n")
    fake.chmod(0o755)
    rows = fetch_assemblies(datasets_bin=str(fake))
    assert [r["taxid"] for r in itertools.islice(rows, 2)] == [7227, 7227]
    rows.close()
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)


def test_parse_assembly_record_full():
    row = parse_assembly_record(ASSEMBLY_RECORD)
    assert row is not None
    assert set(row) == set(ASSEMBLY_COLUMNS)
    assert row["assembly_accession"] == "GCF_000001215.4"
    assert row["taxid"] == 7227
    assert row["assembly_level"] == "Chromosome"
    # numeric string is coerced to int
    assert row["total_sequence_length"] == 143706478
    assert row["contig_n50"] == 21485538
    assert row["gc_percent"] == 42
    assert row["refseq_category"] == "reference genome"
    assert row["release_date"] == "2014-08-01"
    # SOURCE_DATABASE_REFSEQ -> RefSeq
    assert row["source_database"] == "RefSeq"
    # deduped + sorted bioprojects from top-level + lineage
    assert row["bioprojects"] == ["PRJNA13", "PRJNA13812"]
    assert row["download_url"].endswith("/genome/GCF_000001215.4/")


def test_parse_assembly_source_db_genbank():
    rec = {**ASSEMBLY_RECORD, "source_database": "SOURCE_DATABASE_GENBANK"}
    assert parse_assembly_record(rec)["source_database"] == "GenBank"


def test_parse_assembly_missing_taxid_is_dropped():
    rec = {"accession": "GCA_9.1", "organism": {}}
    assert parse_assembly_record(rec) is None


def test_parse_assembly_sparse_record_defaults_to_none():
    rec = {"accession": "GCA_9.1", "organism": {"tax_id": 42}}
    row = parse_assembly_record(rec)
    assert row["taxid"] == 42
    assert row["assembly_level"] is None
    assert row["contig_n50"] is None
    assert row["bioprojects"] == []


def test_parse_report_row_full():
    row = parse_report_row(ANNOTATION_ROW)
    assert row is not None
    assert set(row) == set(ANNOTATION_COLUMNS)
    assert row["annotation_id"] == "f628158077010762f66c13935b5630a3"
    assert row["assembly_accession"] == "GCA_001624475.1"
    assert row["taxid"] == 10090  # string -> int
    assert row["source_database"] == "Ensembl"
    assert row["provider"] == "community"
    # ISO datetime trimmed to a DATE
    assert row["release_date"] == "2018-01-01"
    assert row["gff_url"].endswith(".gff3.gz")
    assert row["gene_count"] == 22685
    assert row["protein_coding_count"] == 20589
    assert row["busco_complete"] == 99.2
    assert row["busco_single_copy"] == 97.7
    assert row["busco_lineage"] == "eukaryota_odb12"


def test_parse_report_row_empty_cells_become_none():
    empty = dict.fromkeys(["busco_lineage", "busco_complete", "busco_single_copy",
                           "busco_duplicated", "root_type_counts", "coding_gene_count",
                           "release_date", "provider"], "")
    row = parse_report_row({**ANNOTATION_ROW, **empty})
    assert row["gene_count"] is None
    assert row["protein_coding_count"] is None
    assert row["busco_complete"] is None
    assert row["busco_lineage"] is None
    assert row["release_date"] is None
    assert row["provider"] is None
    assert row["source_database"] == "Ensembl"


def test_parse_report_row_missing_id_or_taxid_is_dropped():
    assert parse_report_row({**ANNOTATION_ROW, "annotation_id": ""}) is None
    assert parse_report_row({**ANNOTATION_ROW, "taxid": ""}) is None


def _report(monkeypatch, text: str) -> None:
    monkeypatch.setattr(fa, "_report_lines", lambda source: iter(text.splitlines()))


def test_fetch_annotations_reads_the_report(monkeypatch):
    _report(monkeypatch, f"{REPORT_HEADER}\n{REPORT_LINE}\n")
    rows = list(fa.fetch_annotations())
    assert [r["annotation_id"] for r in rows] == ["f628158077010762f66c13935b5630a3"]


@pytest.mark.parametrize(
    "report",
    [
        "",  # empty body
        REPORT_HEADER + "\n",  # header only
        REPORT_HEADER.replace("\tbusco_complete", "") + "\n" + REPORT_LINE,  # column gone
    ],
)
def test_fetch_annotations_fails_on_an_unusable_report(monkeypatch, report):
    """A changed or truncated report must fail the build, not ship no annotations."""
    _report(monkeypatch, report)
    with pytest.raises(RuntimeError):
        list(fa.fetch_annotations())


def test_drop_duplicate_assemblies_keeps_one_row_per_assembly():
    frame = pl.DataFrame(
        {
            "assembly_accession": [
                "GCA_000001405.29",  # human, GenBank
                "GCF_000001405.40",  # its RefSeq copy
                "GCA_000006425.1",  # superseded version
                "GCA_000006425.2",
                "GCF_900000001.1",  # RefSeq-only: kept
            ],
            "taxid": [9606, 9606, 237895, 353151, 1],
        }
    )
    kept = drop_duplicate_assemblies(frame)["assembly_accession"].to_list()
    assert sorted(kept) == ["GCA_000001405.29", "GCA_000006425.2", "GCF_900000001.1"]


class _Reply:
    """A stubbed ENA response: the count endpoint's text, or a TSV body."""

    def __init__(self, text: str = "", tsv: str = "") -> None:
        self.text = text
        self._tsv = tsv.encode()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        pass

    def iter_lines(self, chunk_size: int) -> Iterator[bytes]:
        return iter(self._tsv.splitlines())


def _tsv(taxids: list[int]) -> str:
    return "run_accession\ttax_id\n" + "".join(f"ERR{i}\t{t}\n" for i, t in enumerate(taxids))


def _ena(monkeypatch, bodies: dict[str, list[str]], expected: dict[str, int]) -> None:
    """Stub ENA: ``bodies`` and ``expected`` are keyed by "short" / "long", and each
    search answers with the next body for its query."""
    queue = {kind: iter(b) for kind, b in bodies.items()}

    def post(source, endpoint, query, *, stream=False, **fields):
        kind = "long" if query == fr._LONG_QUERY else "short"
        assert fields.get("format", "tsv") == "tsv"
        if endpoint == "count":
            return _Reply(text=f"count\n{expected[kind]}\n")
        return _Reply(tsv=next(queue[kind]))

    monkeypatch.setattr(fr, "_post", post)


def test_fetch_reads_counts_runs_per_taxon(monkeypatch):
    _ena(
        monkeypatch,
        bodies={"short": [_tsv([9606, 10090])], "long": [_tsv([9606])]},
        expected={"short": 2, "long": 1},
    )
    rows = {r["taxid"]: r for r in fr.fetch_reads()}
    assert rows[9606] == {"taxid": 9606, "short": 1, "long": 1}
    assert rows[10090] == {"taxid": 10090, "short": 1, "long": 0}


@pytest.mark.parametrize(
    "body",
    [
        _tsv([9606]),  # ended early with a clean, shorter body
        _tsv([9606]) + "Request execution cancelled\n",  # an error message mid-stream
        "",  # empty
    ],
)
def test_fetch_reads_rejects_an_incomplete_download(monkeypatch, body):
    """ENA can end a response early; the count endpoint tells."""
    _ena(monkeypatch, bodies={"short": [body]}, expected={"short": 3})
    once = fr._runs_per_taxon.retry_with(stop=stop_after_attempt(1))
    with pytest.raises(RuntimeError, match="of 3 runs|unexpected ENA header"):
        once(ENA, fr._SHORT_QUERY)


def test_fetch_reads_retries_until_the_download_is_complete(monkeypatch):
    _ena(
        monkeypatch,
        bodies={"short": [_tsv([9606]), _tsv([9606, 9606, 10090])]},
        expected={"short": 3},
    )
    counts = fr._runs_per_taxon.retry_with(wait=wait_none())(ENA, fr._SHORT_QUERY)
    assert counts == {9606: 2, 10090: 1}


def test_the_two_queries_split_rna_seq_by_platform():
    assert fr._RNA_SEQ in fr._LONG_QUERY and fr._RNA_SEQ in fr._SHORT_QUERY
    for platform in ("OXFORD_NANOPORE", "PACBIO_SMRT"):
        assert f'instrument_platform="{platform}"' in fr._LONG_QUERY
        assert f'instrument_platform!="{platform}"' in fr._SHORT_QUERY
