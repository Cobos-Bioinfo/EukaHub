"""The biggest gaps: GET /taxons sorted by resources.<resource>.missing, the species of a taxon
still without that resource.

Rebuild/slice-safe: assertions cross-check whatever comes back against
/taxons/{taxid}. Long-read coverage is sparse on prod, and the CI slice carries a
mammal species without data, so Mammalia keeps a long-read gap on both.
"""

from __future__ import annotations

from itertools import pairwise

from eukahub_core.metrics import METRIC_NAMES


def _gaps(client, **params) -> list[dict]:
    response = client.get(
        "/taxons",
        params={
            "within": 2759,
            "sort_by": "resources.long_read_rna_seq.missing",
            "rank": "class",
            **params,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _gap(it: dict, key: str = "long_read_rna_seq") -> int:
    return it["resources"][key]["missing"]


def test_gaps_are_sorted_biggest_first(client):
    items = _gaps(client)
    assert items
    gaps = [_gap(it) for it in items]
    assert gaps == sorted(gaps, reverse=True)
    # Equal gaps: the bigger group first.
    for a, b in pairwise(items):
        if _gap(a) == _gap(b):
            assert a["species"] >= b["species"]


def test_gap_sort_ascending_puts_the_best_covered_first(client):
    gaps = [_gap(it) for it in _gaps(client, sort_order="asc")]
    assert gaps == sorted(gaps)


def test_gaps_stats_match_the_taxon(client):
    """The stats of a gap clade are the ones /taxons/{taxid}/stats serves."""
    params = {"within": 2759, "sort_by": "resources.long_read_rna_seq.missing", "rank": "class", "limit": 1}
    it = client.get("/taxons/stats", params=params).json()["results"][0]
    assert it["taxid"] == _gaps(client, limit=1)[0]["taxid"]
    assert it == client.get(f"/taxons/{it['taxid']}/stats").json()


def test_every_resource_has_a_gap_sort(client):
    for key in METRIC_NAMES:
        gaps = [_gap(it, key) for it in _gaps(client, sort_by=f"resources.{key}.missing")]
        assert gaps == sorted(gaps, reverse=True)


def test_unknown_sort_is_a_422(client):
    assert client.get("/taxons", params={"rank": "class", "sort_by": "resources.xyz.missing"}).status_code == 422
