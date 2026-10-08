"""The release gate: the invariants a build must pass before it is published or
installed, and the comparison of its key counts with the previous Release.

The invariant tests run against the loaded dataset (the full one or the CI slice)
and skip without a database. Each failure case changes the data inside a
transaction that is always rolled back.
"""

from __future__ import annotations

import logging
import os

import psycopg
import pytest
from eukahub_core.metrics import METRICS
from eukahub_core.taxonomy import EUKARYOTA_TAXID
from eukahub_pipeline.build import DEFAULT_DB_URL
from eukahub_pipeline.validate import (
    DataValidationError,
    check_against_previous,
    check_invariants,
    count_drops,
    release_counts,
)

PREVIOUS = {"taxa": 1000, "total_species": 800, "total_assemblies": 70_000}


def test_counts_that_grew_or_moved_a_little_pass():
    current = {"taxa": 990, "total_species": 760, "total_assemblies": 72_000}
    assert count_drops(current, PREVIOUS) == []


def test_a_sharp_drop_is_named_with_its_numbers():
    current = {"taxa": 1000, "total_species": 800, "total_assemblies": 35_000}
    assert count_drops(current, PREVIOUS) == ["total_assemblies 70,000 -> 35,000 (-50.0%)"]


def test_a_count_only_one_release_has_is_skipped():
    assert count_drops({"taxa": 1000, "new_count": 1}, {"taxa": 1000, "old_count": 50}) == []


def test_a_drop_fails_the_build_unless_accepted(caplog):
    current = dict(PREVIOUS, total_species=100)
    with pytest.raises(DataValidationError, match="total_species 800 -> 100"):
        check_against_previous(current, PREVIOUS)
    with caplog.at_level(logging.WARNING):
        check_against_previous(current, PREVIOUS, accept_drops=True)
    assert "accepted" in caplog.text


@pytest.fixture
def conn():
    try:
        conn = psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DB_URL), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("serving Postgres not reachable")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_the_loaded_dataset_passes(conn):
    check_invariants(conn)


def test_release_counts_are_the_eukaryota_totals(conn):
    counts = release_counts(conn)
    assert list(counts) == [
        "taxa",
        "total_species",
        *(m.tsv_count_column for m in METRICS),
        *(m.tsv_total_column for m in METRICS),
    ]
    assert all(n > 0 for n in counts.values())
    assert counts["total_assemblies"] == conn.execute("SELECT count(*) FROM assembly").fetchone()[0]
    assert counts["taxa"] > counts["total_species"] >= counts["species_with_assemblies"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            (
                f"DELETE FROM clade_features WHERE taxid = {EUKARYOTA_TAXID}; "
                f"DELETE FROM taxon WHERE taxid = {EUKARYOTA_TAXID}"
            ),
            "not in the taxon table",
        ),
        (
            f"DELETE FROM clade_features WHERE taxid = {EUKARYOTA_TAXID}",
            "no clade_features row",
        ),
        (
            f"UPDATE clade_features SET c_lng = 0 WHERE taxid = {EUKARYOTA_TAXID}",
            "no species has data for: Long-Read RNA-Seq",
        ),
        # The RefSeq copy of an assembly already loaded as GenBank; Eukaryota's
        # total follows so that only the repeat is wrong.
        (
            (
                "INSERT INTO assembly (assembly_accession, taxid, assembly_level, contig_n50, "
                "total_sequence_length) SELECT 'GCF_' || substr(assembly_accession, 5), taxid, "
                "assembly_level, contig_n50, total_sequence_length FROM assembly "
                "WHERE assembly_accession LIKE 'GCA_%' LIMIT 1; "
                f"UPDATE clade_features SET s_ass = s_ass + 1 WHERE taxid = {EUKARYOTA_TAXID}"
            ),
            "1 assembly rows repeat an assembly number",
        ),
        ("UPDATE assembly SET contig_n50 = NULL", r"assembly.contig_n50 is filled on 0%"),
        ("UPDATE annotation SET busco_complete = NULL", r"annotation.busco_complete is filled"),
    ],
    ids=[
        "no Eukaryota taxon",
        "no Eukaryota rollup",
        "a resource without data",
        "a repeated assembly",
        "a renamed assembly field",
        "a renamed annotation field",
    ],
)
def test_a_broken_dataset_fails_with_a_clear_message(conn, change, message):
    with conn.transaction(force_rollback=True):
        conn.execute(change)
        with pytest.raises(DataValidationError, match=message):
            check_invariants(conn)
