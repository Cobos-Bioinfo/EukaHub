"""GET /taxons in general: the page envelope, chosen taxids, cursors and caps."""

from __future__ import annotations

import pytest
from eukahub_api.main import MAX_TAXIDS
from eukahub_core.metrics import QUALITY_KEYS


def test_page_envelope(client):
    body = client.get("/taxons", params={"parent": 2759, "limit": 2}).json()
    assert set(body) == {"total", "limit", "next", "previous", "results"}
    assert body["limit"] == 2 and body["previous"] is None
    item = body["results"][0]
    assert {"taxid", "name", "rank", "context", "n_rows", "resources", "composition"} <= set(item)
    assert item["direct"] is None


def test_taxids_lists_those_taxa(client):
    """Mammalia and Homo sapiens are in the full dataset and the CI slice. Unknown
    taxids match nothing."""
    body = client.get("/taxons", params={"taxids": "9606,40674,99999999"}).json()
    assert sorted(it["taxid"] for it in body["results"]) == [9606, 40674]
    assert body["total"] == 2
    for it in body["results"]:
        taxon = client.get(f"/taxons/{it['taxid']}").json()
        assert it["n_rows"] == taxon["n_rows"]
        assert it["resources"] == taxon["resources"]
        assert "stats" not in it


@pytest.mark.parametrize(
    "params",
    [
        {"taxids": "9606,40674,99999999"},
        {"within": 40674, "rank": "order", "sort_by": "gap_ass", "limit": 4},
        {"within": 2759, "rank": "species", "sort_by": "s_ass", "limit": 5},
        {"q": "homo", "limit": 3},
    ],
)
def test_stats_follow_the_list_page_for_page(client, params):
    """/taxons/stats holds the same taxa as /taxons for the same parameters, in the
    same order and with the same cursors, and each taxon's stats are the ones
    /taxons/{taxid} serves."""
    listed = client.get("/taxons", params=params).json()
    stats = client.get("/taxons/stats", params=params).json()
    assert [s["taxid"] for s in stats["results"]] == [it["taxid"] for it in listed["results"]]
    assert {k: stats[k] for k in ("total", "limit", "next", "previous")} == {
        k: listed[k] for k in ("total", "limit", "next", "previous")
    }
    for s in stats["results"][:3]:
        assert set(s) == {"taxid", "name", "stats"}
        assert [v["key"] for v in s["stats"]] == list(QUALITY_KEYS)
        assert s["stats"] == client.get(f"/taxons/{s['taxid']}").json()["stats"]


def test_stats_page_with_the_list_cursor(client):
    params = {"within": 2759, "rank": "class", "limit": 4}
    first = client.get("/taxons", params=params).json()
    listed = client.get("/taxons", params={**params, "cursor": first["next"]}).json()
    stats = client.get("/taxons/stats", params={**params, "cursor": first["next"]}).json()
    assert [s["taxid"] for s in stats["results"]] == [it["taxid"] for it in listed["results"]]
    for s in stats["results"]:
        busco = next(v["value"] for v in s["stats"] if v["key"] == "busco")
        assert busco is None or 0.0 <= busco <= 100.0


@pytest.mark.parametrize(
    ("taxids", "detail"),
    [
        ("9606,abc", "is not a taxid"),
        ("-5", "is not a taxid"),
        ("²", "is not a taxid"),
        ("1" * 5000, "is not a taxid"),
        (",".join(str(i) for i in range(1, MAX_TAXIDS + 2)), "at most"),
    ],
)
def test_taxids_are_checked(client, taxids, detail):
    response = client.get("/taxons", params={"taxids": taxids})
    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_filters_combine(client):
    """within + rank + taxids: only the chosen taxa that also match the rest."""
    body = client.get(
        "/taxons", params={"within": 40674, "rank": "species", "taxids": "9606,8782"}
    ).json()
    assert [it["taxid"] for it in body["results"]] == [9606]


def test_backward_cursor_returns_the_previous_page(client):
    params = {"within": 2759, "rank": "class", "limit": 4}
    first = client.get("/taxons", params=params).json()
    second = client.get("/taxons", params={**params, "cursor": first["next"]}).json()
    back = client.get("/taxons", params={**params, "cursor": second["previous"]}).json()
    assert [it["taxid"] for it in back["results"]] == [it["taxid"] for it in first["results"]]
    assert back["previous"] is None


def test_cursor_of_another_sort_is_rejected(client):
    first = client.get("/taxons", params={"parent": 2759, "limit": 2}).json()
    resp = client.get(
        "/taxons", params={"parent": 2759, "limit": 2, "sort_by": "s_ass", "cursor": first["next"]}
    )
    assert resp.status_code == 422


def test_list_is_cacheable(client):
    r = client.get("/taxons", params={"parent": 2759, "limit": 1})
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")
