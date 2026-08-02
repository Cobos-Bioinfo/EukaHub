"""Tests for GET /clade/{taxid}/summary.

DB-backed tests use the shared ``client`` fixture (see conftest.py), which
skips when Postgres is down. The column-order guard needs no DB and always
runs.
"""

from __future__ import annotations

from dataclasses import fields

import psycopg
import pytest
from eukahub_api.db import database_url
from eukahub_core.metrics import (
    COMPOSITION_COLUMNS,
    COVERAGE_KEYS,
    TOTAL_KEYS,
    CladeMetadata,
)


def test_summary_eukaryota(client):
    """Eukaryota's summary: stable taxonomy facts + structural invariants that
    survive a data rebuild. Exact counts change on every refresh, so we assert
    relationships (covered <= species, total >= covered, percent math) rather
    than frozen numbers."""
    body = client.get("/clade/2759/summary").json()
    assert body["taxid"] == 2759
    assert body["name"] == "Eukaryota"
    assert body["rank"] == "domain"
    assert body["is_infraspecific"] is False
    # n_rows is the count of species in the subtree. Assert exactly that (a
    # stronger, dataset-size-agnostic invariant than a magic threshold), so it
    # holds on the full production DB *and* on the compact CI seed slice.
    with psycopg.connect(database_url()) as conn:
        species = conn.execute(
            "SELECT count(*) FROM taxon "
            "WHERE rank = 'species' AND path <@ (SELECT path FROM taxon WHERE taxid = 2759)"
        ).fetchone()[0]
    assert body["n_rows"] == species

    assert set(body["resources"]) == {"ass", "ann", "rna", "lng"}
    for res in body["resources"].values():
        assert 0 <= res["covered"] <= body["n_rows"]  # covered species <= all species
        assert res["total"] >= res["covered"]  # >=1 resource per covered species
        assert res["percent"] == pytest.approx(
            res["covered"] / body["n_rows"] * 100, abs=0.01
        )

    # Assembly composition: the per-level split can't exceed the assemblies
    # total, and the reference-genome count can't exceed it either.
    comp = body["composition"]
    level_sum = comp["complete"] + comp["chromosome"] + comp["scaffold"] + comp["contig"]
    assert level_sum <= body["resources"]["ass"]["total"]
    assert 0 <= comp["reference"] <= body["resources"]["ass"]["total"]


def test_summary_not_found(client):
    resp = client.get("/clade/999999999/summary")
    assert resp.status_code == 404


def test_summary_zero_filled(client):
    """A taxon present in `taxon` but absent from the rollup returns zeros."""
    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "SELECT t.taxid FROM taxon t "
            "LEFT JOIN clade_features f USING (taxid) "
            "WHERE f.taxid IS NULL LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("every taxon has a rollup row — nothing to zero-fill")

    body = client.get(f"/clade/{row[0]}/summary").json()
    assert body["n_rows"] == 0
    for key in ("ass", "ann", "rna", "lng"):
        assert body["resources"][key] == {"covered": 0, "total": 0, "percent": 0.0}


def test_summary_infraspecific(client):
    """A below-species taxon reports is_infraspecific, n_rows==1, and its own
    directly-attached totals (dynamically pick a data-carrying subspecies so the
    test doesn't pin to a specific taxid that could drift)."""
    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "SELECT t.taxid, f.s_ass FROM taxon t JOIN clade_features f USING (taxid) "
            "WHERE t.rank = 'subspecies' AND f.s_ass > 0 "
            "AND t.path <@ (SELECT path FROM taxon WHERE taxid = 2759) "
            "ORDER BY f.s_ass DESC LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("no subspecies with assemblies in this dataset")
    taxid, s_ass = row

    body = client.get(f"/clade/{taxid}/summary").json()
    assert body["is_infraspecific"] is True
    assert body["rank"] == "subspecies"
    assert body["n_rows"] == 1  # a leaf unit, not a clade of species
    assert body["resources"]["ass"]["total"] == s_ass


def test_summary_species_not_counted_upward(client):
    """A species is not infraspecific, and its subspecies never inflate it: the
    subtree species count stays 1 (itself), so subspecies data is not rolled up.
    Homo sapiens (9606) has two subspecies (Neanderthal, Denisova)."""
    body = client.get("/clade/9606/summary").json()
    assert body["rank"] == "species"
    assert body["is_infraspecific"] is False
    assert body["n_rows"] == 1


def test_summary_clade_not_infraspecific(client):
    assert client.get("/clade/2759/summary").json()["is_infraspecific"] is False


def test_clade_metadata_field_order():
    """Guard: CladeMetadata field order == the SELECT column order in
    queries.py, so ``CladeMetadata(taxid, *features)`` stays correct."""
    names = [f.name for f in fields(CladeMetadata)]
    assert names == ["taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS, *COMPOSITION_COLUMNS]
