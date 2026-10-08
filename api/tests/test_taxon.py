"""Tests for GET /taxons/{taxid}: one taxon, its lineage, counts and quality stats.

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
    METRIC_NAMES,
    QUALITY_KEYS,
    TOTAL_KEYS,
    CladeMetadata,
)


def test_taxon_eukaryota(client):
    """Eukaryota's summary: stable taxonomy facts + structural invariants that
    survive a data rebuild. Exact counts change on every refresh, so we assert
    relationships (covered <= species, total >= covered, percent math) rather
    than frozen numbers."""
    body = client.get("/taxons/2759").json()
    assert body["taxid"] == 2759
    assert body["name"] == "Eukaryota"
    assert body["rank"] == "domain"
    assert body["is_infraspecific"] is False
    # `species` is the count of species in the subtree. Assert exactly that (a
    # stronger, dataset-size-agnostic invariant than a magic threshold), so it
    # holds on the full production DB *and* on the compact CI seed slice.
    with psycopg.connect(database_url()) as conn:
        species = conn.execute(
            "SELECT count(*) FROM taxon "
            "WHERE rank = 'species' AND path <@ (SELECT path FROM taxon WHERE taxid = 2759)"
        ).fetchone()[0]
    assert body["species"] == species

    assert list(body["resources"]) == list(METRIC_NAMES)
    for res in body["resources"].values():
        assert 0 <= res["covered"] <= body["species"]  # covered species <= all species
        assert res["missing"] == body["species"] - res["covered"]
        assert res["total"] >= res["covered"]  # >=1 resource per covered species
        assert res["percent"] == pytest.approx(
            res["covered"] / body["species"] * 100, abs=0.01
        )

    # Assembly composition: the per-level split can't exceed the assemblies
    # total, and the reference-genome count can't exceed it either.
    comp = body["composition"]
    level_sum = comp["complete"] + comp["chromosome"] + comp["scaffold"] + comp["contig"]
    assert level_sum <= body["resources"]["assemblies"]["total"]
    assert 0 <= comp["reference"] <= body["resources"]["assemblies"]["total"]


def test_taxon_not_found(client):
    resp = client.get("/taxons/999999999")
    assert resp.status_code == 404


def test_taxon_zero_filled(client):
    """A taxon present in `taxon` but absent from the rollup returns zeros."""
    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "SELECT t.taxid FROM taxon t "
            "LEFT JOIN clade_features f USING (taxid) "
            "WHERE f.taxid IS NULL LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("every taxon has a rollup row — nothing to zero-fill")

    body = client.get(f"/taxons/{row[0]}").json()
    assert body["species"] == 0
    for key in METRIC_NAMES:
        assert body["resources"][key] == {"covered": 0, "missing": 0, "total": 0, "percent": 0.0}


def _first(sql: str) -> tuple | None:
    with psycopg.connect(database_url()) as conn:
        return conn.execute(sql).fetchone()


def _children_totals(client, taxid: int) -> dict[str, int]:
    items = client.get("/taxons", params={"parent": taxid, "limit": 1000}).json()["results"]
    return {k: sum(i["resources"][k]["total"] for i in items) for k in METRIC_NAMES}


def test_taxon_infraspecific(client):
    """A below-species taxon reports is_infraspecific, species == 1, and its subtree
    totals (dynamically pick a data-carrying subspecies so the test doesn't pin
    to a specific taxid that could drift)."""
    row = _first(
        "SELECT t.taxid, f.s_ass FROM taxon t JOIN clade_features f USING (taxid) "
        "WHERE t.rank = 'subspecies' AND f.s_ass > 0 "
        "AND t.path <@ (SELECT path FROM taxon WHERE taxid = 2759) "
        "ORDER BY f.s_ass DESC LIMIT 1"
    )
    if row is None:
        pytest.skip("no subspecies with assemblies in this dataset")
    taxid, s_ass = row

    body = client.get(f"/taxons/{taxid}").json()
    assert body["is_infraspecific"] is True
    assert body["rank"] == "subspecies"
    assert body["species"] == 1  # a leaf unit, not a clade of species
    assert body["resources"]["assemblies"]["total"] == s_ass
    assert body["direct"] is not None


def test_taxon_species_includes_subspecies_data(client):
    """A species with data on a subspecies counts that data: its totals equal the
    records under it, it stays one species, and its direct records plus its
    children's totals add up to its totals."""
    row = _first(
        "SELECT p.taxid FROM taxon t JOIN clade_features f USING (taxid) "
        "JOIN taxon p ON p.taxid = t.parent_id "
        "WHERE t.rank = 'subspecies' AND p.rank = 'species' AND f.s_ass > 0 LIMIT 1"
    )
    if row is None:
        pytest.skip("no subspecies with assemblies in this dataset")
    taxid = row[0]

    body = client.get(f"/taxons/{taxid}").json()
    assert body["rank"] == "species"
    assert body["is_infraspecific"] is False
    assert body["species"] == 1
    assemblies = client.get("/assemblies", params={"within": taxid, "limit": 1}).json()
    assert body["resources"]["assemblies"]["total"] == assemblies["total"]
    assert body["resources"]["assemblies"]["covered"] == 1

    below = _children_totals(client, taxid)
    assert below["assemblies"] > 0
    for key, value in body["resources"].items():
        assert body["direct"][key] + below[key] == value["total"]


def test_taxon_informal_species(client):
    """An informal species is one unit that is not a species: the clades above it
    count its records but not it."""
    row = _first(
        "SELECT t.taxid, t.parent_id FROM taxon t JOIN clade_features f USING (taxid) "
        "WHERE t.rank = 'informal species' AND f.s_ass > 0 LIMIT 1"
    )
    if row is None:
        pytest.skip("no informal species with assemblies in this dataset")
    taxid, parent = row

    body = client.get(f"/taxons/{taxid}").json()
    assert body["rank"] == "informal species"
    assert body["is_infraspecific"] is False
    assert body["species"] == 1
    assert body["direct"] is not None
    parent_body = client.get(f"/taxons/{parent}").json()
    species_below = _first(
        "SELECT count(*) FROM taxon WHERE rank = 'species' "
        f"AND path <@ (SELECT path FROM taxon WHERE taxid = {int(parent)})"
    )[0]
    assert parent_body["species"] == species_below
    assert parent_body["resources"]["assemblies"]["total"] >= body["resources"]["assemblies"]["total"]


def test_taxon_clade_totals_match_records(client):
    """A clade's totals count every record under it, whatever rank it sits on."""
    body = client.get("/taxons/2759").json()
    assert body["direct"] is None
    for key in ("assemblies", "annotations"):
        records = client.get(f"/{key}", params={"within": 2759, "limit": 1}).json()
        assert body["resources"][key]["total"] == records["total"]


def test_taxon_clade_not_infraspecific(client):
    assert client.get("/taxons/2759").json()["is_infraspecific"] is False


def test_taxon_is_the_object_the_list_returns(client):
    """/taxons/{taxid} and /taxons share one schema and one builder."""
    for taxid in (2759, 40674, 9606):
        one = client.get(f"/taxons/{taxid}").json()
        assert client.get("/taxons", params={"taxids": taxid}).json()["results"] == [one]


def test_taxon_ancestors_homo_sapiens(client):
    lin = client.get("/taxons/9606/ancestors").json()
    assert lin[0]["taxid"] == 1  # root first
    assert lin[-1] == client.get("/taxons/9606").json()  # the taxon itself last
    assert any(a["taxid"] == 2759 and a["name"] == "Eukaryota" for a in lin)
    taxids = [a["taxid"] for a in lin]
    assert len(taxids) == len(set(taxids))
    # Every ancestor contains the next, so species counts never grow downwards.
    counts = [a["species"] for a in lin]
    assert counts == sorted(counts, reverse=True)


def test_taxon_ancestors_of_the_root(client):
    assert [a["taxid"] for a in client.get("/taxons/1/ancestors").json()] == [1]


def test_taxon_stats(client):
    """The stats cover every record under the taxon: one per QUALITY_STATS key,
    with BUSCO a percentage."""
    body = client.get("/taxons/9606/stats").json()
    assert body["taxid"] == 9606 and body["name"] == "Homo sapiens"
    assert [s["key"] for s in body["stats"]] == list(QUALITY_KEYS)
    stats = {s["key"]: s["value"] for s in body["stats"]}
    assert stats["genome_size"] > 0 and stats["contig_n50"] > 0  # human has genomes
    assert 0.0 <= stats["busco"] <= 100.0


def test_taxon_sub_resources_of_an_unknown_taxon(client):
    assert client.get("/taxons/999999999/ancestors").status_code == 404
    assert client.get("/taxons/999999999/stats").status_code == 404


def test_taxon_has_children(client):
    assert client.get("/taxons/9605").json()["has_children"] is True  # Homo -> species
    kids = client.get("/taxons", params={"parent": 9606}).json()["results"]
    leaf = next(k for k in kids if not k["has_children"])
    assert client.get(f"/taxons/{leaf['taxid']}").json()["has_children"] is False


def test_clade_metadata_field_order():
    """Guard: CladeMetadata field order == the SELECT column order in
    queries.py, so ``CladeMetadata(taxid, *features)`` stays correct."""
    names = [f.name for f in fields(CladeMetadata)]
    assert names == ["taxid", "n_rows", *COVERAGE_KEYS, *TOTAL_KEYS, *COMPOSITION_COLUMNS]
