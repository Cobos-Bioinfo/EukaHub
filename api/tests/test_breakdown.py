"""Tests for GET /clade/{taxid}/breakdown against the live DB.

Uses Eukaryota (2759) broken down at phylum — the worst-case subtree — and
asserts the ported filter/sort/limit semantics rather than exact per-phylum
numbers (which move as the dataset is rebuilt).
"""

from __future__ import annotations

from itertools import pairwise


def _is_descending(values: list[float]) -> bool:
    return all(a >= b for a, b in pairwise(values))


def _totals(items: list[dict], key: str) -> list[int]:
    return [it["resources"][key]["total"] for it in items]


def test_breakdown_root_and_shape(client):
    body = client.get("/clade/2759/breakdown?rank=phylum&limit=10").json()
    assert body["root"] == {"taxid": 2759, "name": "Eukaryota", "rank": "domain"}
    assert body["rank"] == "phylum"
    assert body["returned"] == len(body["items"])
    assert body["returned"] <= 10
    assert body["total_matches"] >= body["returned"]
    assert body["items"], "Eukaryota should have phyla with data"
    assert all(it["rank"] == "phylum" for it in body["items"])


def test_breakdown_default_sort_is_species_count(client):
    # No sort param → default n_rows (species count), descending.
    body = client.get("/clade/2759/breakdown?rank=phylum&limit=25").json()
    assert _is_descending([it["n_rows"] for it in body["items"]])


def test_breakdown_sort_by_total_assemblies(client):
    body = client.get("/clade/2759/breakdown?rank=phylum&sort=s_ass&limit=25").json()
    assert _is_descending(_totals(body["items"], "ass"))


def test_breakdown_exclude_empty_default(client):
    # Default exclude_empty=True → every returned taxon has data somewhere.
    body = client.get("/clade/2759/breakdown?rank=phylum&limit=50").json()
    for it in body["items"]:
        assert any(it["resources"][k]["covered"] > 0 for k in ("ass", "ann", "rna", "lng"))


def test_breakdown_exclude_empty_false_matches_more(client):
    on = client.get("/clade/2759/breakdown?rank=phylum&exclude_empty=true").json()
    off = client.get("/clade/2759/breakdown?rank=phylum&exclude_empty=false").json()
    assert off["total_matches"] >= on["total_matches"]


def test_breakdown_filter_and(client):
    body = client.get(
        "/clade/2759/breakdown?rank=phylum&filter=ass&filter=ann&logic=AND&limit=50"
    ).json()
    for it in body["items"]:
        assert it["resources"]["ass"]["covered"] > 0
        assert it["resources"]["ann"]["covered"] > 0


def test_breakdown_filter_or_is_superset_of_and(client):
    base = "/clade/2759/breakdown?rank=phylum&filter=ass&filter=ann"
    and_body = client.get(f"{base}&logic=AND").json()
    or_body = client.get(f"{base}&logic=OR").json()
    # Every OR row satisfies at least one; AND is a subset, so OR matches >= AND.
    for it in or_body["items"]:
        assert it["resources"]["ass"]["covered"] > 0 or it["resources"]["ann"]["covered"] > 0
    assert or_body["total_matches"] >= and_body["total_matches"]


def test_breakdown_limit_caps_returned(client):
    body = client.get("/clade/2759/breakdown?rank=phylum&limit=3").json()
    assert body["returned"] <= 3
    assert body["total_matches"] >= body["returned"]


def test_breakdown_invalid_rank_422(client):
    # "kingdom" is a real NCBI rank but not in ALLOWED_RANKS → validation error.
    assert client.get("/clade/2759/breakdown?rank=kingdom").status_code == 422


def test_breakdown_missing_rank_422(client):
    assert client.get("/clade/2759/breakdown").status_code == 422


def test_breakdown_bad_root_404(client):
    assert client.get("/clade/999999999/breakdown?rank=phylum").status_code == 404
