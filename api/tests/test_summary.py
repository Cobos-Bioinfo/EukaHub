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
from eukahub_core.metrics import COVERAGE_KEYS, TOTAL_KEYS, CladeMetadata

# Eukaryota (2759) — the Phase-1-validated reference row, column order
# taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng.
EUKARYOTA = {
    "taxid": 2759,
    "name": "Eukaryota",
    "rank": "domain",
    "n_rows": 1647009,
    "ass": {"covered": 25505, "total": 63371},
    "ann": {"covered": 7511, "total": 14237},
    "rna": {"covered": 34718, "total": 8081230},
    "lng": {"covered": 2010, "total": 118584},
}


def test_summary_eukaryota(client):
    body = client.get("/clade/2759/summary").json()
    assert body["taxid"] == EUKARYOTA["taxid"]
    assert body["name"] == EUKARYOTA["name"]
    assert body["rank"] == EUKARYOTA["rank"]
    assert body["n_rows"] == EUKARYOTA["n_rows"]

    for key in ("ass", "ann", "rna", "lng"):
        res = body["resources"][key]
        assert res["covered"] == EUKARYOTA[key]["covered"]
        assert res["total"] == EUKARYOTA[key]["total"]
        expected_pct = round(EUKARYOTA[key]["covered"] / EUKARYOTA["n_rows"] * 100, 2)
        assert res["percent"] == pytest.approx(expected_pct)


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
    assert names == ["taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS]
