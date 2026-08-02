"""Network-free tests for the fetch parsers.

The parsers (``parse_assembly_record`` / ``parse_annotation_record``) are pure,
so we exercise them on captured real-shaped records — no datasets CLI, no
Annotrieve. The live fetch wrappers are covered by manual smoke runs, not CI.
"""

from __future__ import annotations

from eukahub_pipeline.fetch_annotations import (
    ANNOTATION_COLUMNS,
    parse_annotation_record,
)
from eukahub_pipeline.fetch_assemblies import (
    ASSEMBLY_COLUMNS,
    parse_assembly_record,
)

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
ANNOTATION_RECORD = {
    "annotation_id": "f628158077010762f66c13935b5630a3",
    "assembly_accession": "GCA_001624475.1",
    "taxid": "10090",  # Annotrieve sends taxid as a string
    "source_file_info": {
        "database": "Ensembl",
        "provider": "community",
        "release_date": "2018-01-01T00:00:00",
        "url_path": "https://ftp.ebi.ac.uk/pub/.../annotation.gff.gz",
    },
    "features_summary": {"root_type_counts": {"gene": 22685, "chromosome": 20}},
    "features_statistics": {"gene_category_stats": {"coding": {"total_count": 20589}}},
    "busco": {
        "busco_lineage": "eukaryota_odb12",
        "complete": 99.2,
        "single_copy": 97.7,
        "duplicated": 1.6,
    },
}


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


def test_parse_annotation_record_full():
    row = parse_annotation_record(ANNOTATION_RECORD)
    assert row is not None
    assert set(row) == set(ANNOTATION_COLUMNS)
    assert row["annotation_id"] == "f628158077010762f66c13935b5630a3"
    assert row["assembly_accession"] == "GCA_001624475.1"
    assert row["taxid"] == 10090  # string -> int
    assert row["source_database"] == "Ensembl"
    assert row["provider"] == "community"
    # ISO datetime trimmed to a DATE
    assert row["release_date"] == "2018-01-01"
    assert row["gff_url"].endswith(".gff.gz")
    assert row["gene_count"] == 22685
    assert row["protein_coding_count"] == 20589
    assert row["busco_complete"] == 99.2
    assert row["busco_single_copy"] == 97.7
    assert row["busco_lineage"] == "eukaryota_odb12"


def test_parse_annotation_missing_busco_and_stats():
    rec = {
        "annotation_id": "abc",
        "taxid": "7227",
        "source_file_info": {"database": "NCBI"},
    }
    row = parse_annotation_record(rec)
    assert row["gene_count"] is None
    assert row["protein_coding_count"] is None
    assert row["busco_complete"] is None
    assert row["busco_lineage"] is None
    assert row["source_database"] == "NCBI"


def test_parse_annotation_missing_id_is_dropped():
    assert parse_annotation_record({"taxid": "7227"}) is None
