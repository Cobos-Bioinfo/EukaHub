"""End-to-end tests for GET /clade/{taxid}/summary against the live DB.

These hit the docker-compose Postgres (the Phase 1 dataset). If it isn't
reachable the whole module skips, so the suite stays green without infra.
Run with the stack up:  uv run --package eukahub-api pytest api/tests
"""

from __future__ import annotations

from dataclasses import fields

import psycopg
import pytest
from eukahub_api.db import database_url
from eukahub_api.main import app
from eukahub_core.metrics import COVERAGE_KEYS, TOTAL_KEYS, CladeMetadata
from fastapi.testclient import TestClient

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


def _db_available() -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=3):
            return True
    except Exception:  # noqa: BLE001 — any connection failure means "skip"
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="serving Postgres not reachable")


@pytest.fixture(scope="module")
def client():
    # `with` triggers the lifespan, opening the connection pool.
    with TestClient(app) as c:
        yield c


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


def test_clade_metadata_field_order():
    """Guard: CladeMetadata field order == the SELECT column order in
    queries.py, so ``CladeMetadata(taxid, *features)`` stays correct."""
    names = [f.name for f in fields(CladeMetadata)]
    assert names == ["taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS]
