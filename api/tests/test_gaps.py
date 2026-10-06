"""The biggest gaps: GET /taxons sorted by gap_<resource>, the species of a taxon
still without that resource.

Rebuild/slice-safe: assertions cross-check whatever comes back against
/taxons/{taxid}. Long-read coverage is sparse on prod, and the CI slice carries a
mammal species without data, so Mammalia keeps a long-read gap on both.
"""

from __future__ import annotations

from itertools import pairwise


def _gaps(client, **params) -> list[dict]:
    response = client.get(
        "/taxons", params={"within": 2759, "sort_by": "gap_lng", "rank": "class", **params}
    )
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _gap(it: dict, key: str = "lng") -> int:
    return it["n_rows"] - it["resources"][key]["covered"]


def test_gaps_are_sorted_biggest_first(client):
    items = _gaps(client)
    assert items
    gaps = [_gap(it) for it in items]
    assert gaps == sorted(gaps, reverse=True)
    # Equal gaps: the bigger group first.
    for a, b in pairwise(items):
        if _gap(a) == _gap(b):
            assert a["n_rows"] >= b["n_rows"]


def test_gap_sort_ascending_puts_the_best_covered_first(client):
    gaps = [_gap(it) for it in _gaps(client, sort_order="asc")]
    assert gaps == sorted(gaps)


def test_gaps_stats_match_the_taxon(client):
    """The stats of a gap clade are the ones /taxons/{taxid} serves."""
    params = {"within": 2759, "sort_by": "gap_lng", "rank": "class", "limit": 1}
    it = client.get("/taxons/stats", params=params).json()["results"][0]
    assert it["taxid"] == _gaps(client, limit=1)[0]["taxid"]
    assert it["stats"] == client.get(f"/taxons/{it['taxid']}").json()["stats"]


def test_every_resource_has_a_gap_sort(client):
    for key in ("ass", "ann", "rna", "lng"):
        gaps = [_gap(it, key) for it in _gaps(client, sort_by=f"gap_{key}")]
        assert gaps == sorted(gaps, reverse=True)


def test_unknown_sort_is_a_422(client):
    assert client.get("/taxons", params={"rank": "class", "sort_by": "gap_xyz"}).status_code == 422
