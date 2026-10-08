"""The taxa of a rank under a taxon: GET /taxons?within=...&rank=..., the data map.

Uses Eukaryota (2759) broken down at phylum, the worst-case subtree, and asserts
the filter/sort/limit semantics rather than per-phylum numbers.
"""

from __future__ import annotations

from itertools import pairwise

import psycopg
from eukahub_api.db import database_url


def _is_descending(values: list[float]) -> bool:
    return all(a >= b for a, b in pairwise(values))


def _phyla(client, **params) -> dict:
    response = client.get("/taxons", params={"within": 2759, "rank": "phylum", **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_breakdown_shape(client):
    body = _phyla(client, limit=10)
    assert len(body["results"]) <= 10
    assert body["total"] >= len(body["results"])
    assert body["results"], "Eukaryota has phyla"
    assert all(it["rank"] == "phylum" for it in body["results"])


def test_breakdown_total_is_every_taxon_of_the_rank_below(client):
    with psycopg.connect(database_url()) as conn:
        (expected,) = conn.execute(
            "SELECT count(*) FROM taxon WHERE rank = 'phylum' "
            "AND path <@ (SELECT path FROM taxon WHERE taxid = 2759)"
        ).fetchone()
    assert _phyla(client, limit=1)["total"] == expected


def test_breakdown_default_sort_is_species_count(client):
    assert _is_descending([it["n_rows"] for it in _phyla(client, limit=25)["results"]])


def test_breakdown_sort_by_total_assemblies_both_ways(client):
    desc = [it["resources"]["ass"]["total"] for it in _phyla(client, sort_by="s_ass")["results"]]
    asc = [
        it["resources"]["ass"]["total"]
        for it in _phyla(client, sort_by="s_ass", sort_order="asc")["results"]
    ]
    assert _is_descending(desc)
    assert _is_descending(asc[::-1])


def test_breakdown_exclude_empty(client):
    on = _phyla(client, exclude_empty="true", limit=50)
    off = _phyla(client, limit=1)
    for it in on["results"]:
        assert any(it["resources"][k]["covered"] > 0 for k in ("ass", "ann", "rna", "lng"))
    assert off["total"] >= on["total"]


def test_breakdown_filter_and(client):
    for it in _phyla(client, filter=["ass", "ann"], logic="and", limit=50)["results"]:
        assert it["resources"]["ass"]["covered"] > 0
        assert it["resources"]["ann"]["covered"] > 0


def test_breakdown_filter_or_is_superset_of_and(client):
    and_body = _phyla(client, filter=["ass", "ann"], logic="and")
    or_body = _phyla(client, filter=["ass", "ann"], logic="or")
    for it in or_body["results"]:
        assert it["resources"]["ass"]["covered"] > 0 or it["resources"]["ann"]["covered"] > 0
    assert or_body["total"] >= and_body["total"]


def test_breakdown_limit(client):
    assert len(_phyla(client, limit=3)["results"]) <= 3
    assert client.get("/taxons", params={"within": 2759, "limit": 1001}).status_code == 422


def test_breakdown_invalid_rank_422(client):
    # "superclass" is a real NCBI rank but not one of the major ranks `rank` takes.
    assert client.get("/taxons", params={"within": 2759, "rank": "superclass"}).status_code == 422


def test_breakdown_by_kingdom(client):
    body = client.get("/taxons", params={"within": 2759, "rank": "kingdom"}).json()
    assert body["results"] and all(it["rank"] == "kingdom" for it in body["results"])


def test_breakdown_unknown_root_404(client):
    assert client.get("/taxons", params={"within": 999999999, "rank": "phylum"}).status_code == 404
