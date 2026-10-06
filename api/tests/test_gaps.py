"""Tests for GET /gaps — the biggest under-sequenced groups ("Where are the gaps?").

Rebuild/slice-safe: the assertions never pin a specific clade to a fixed rank in
the top-N (prod has far bigger clades than the CI slice), so they cross-check
whatever comes back against /taxons/{taxid} instead. The one place a
non-empty result is needed uses resource=lng at class level: long-read coverage
is sparse on prod, and the CI slice carries a mammal species without data, so
Mammalia keeps a gap on both.
"""

from __future__ import annotations


def test_gaps_shape_and_defaults(client):
    """Default call: Eukaryota, order level, assemblies. Shape + per-item
    invariants hold whether or not the (slice-dependent) item list is empty."""
    body = client.get("/gaps").json()
    assert body["root"]["taxid"] == 2759
    assert body["root"]["name"] == "Eukaryota"
    assert body["rank"] == "order"
    assert body["resource"] == "ass"
    assert body["returned"] == len(body["items"])
    assert body["total_matches"] >= body["returned"]

    gaps = [it["gap"] for it in body["items"]]
    assert gaps == sorted(gaps, reverse=True)  # biggest gap first
    for it in body["items"]:
        assert it["rank"] == "order"
        assert it["gap"] == it["n_rows"] - it["covered"]
        assert it["gap"] > 0  # fully-covered clades are omitted
        assert it["covered"] <= it["n_rows"]
        assert 0.0 <= it["percent"] <= 100.0


def test_gaps_non_empty_and_sorted(client):
    """A rank/resource with a gap on both the slice and prod returns a sorted,
    all-same-rank list of clades that each have a real gap."""
    body = client.get("/gaps", params={"rank": "class", "resource": "lng"}).json()
    items = body["items"]
    assert body["resource"] == "lng"
    assert len(items) >= 1  # Mammalia keeps a long-read gap on the slice
    gaps = [it["gap"] for it in items]
    assert gaps == sorted(gaps, reverse=True)
    assert all(it["rank"] == "class" for it in items)
    assert all(it["gap"] > 0 for it in items)


def test_gaps_match_summary(client):
    """Each ranked item is the same rollup the summary endpoint serves, and the
    gap is derived from it — no separate source of truth."""
    body = client.get("/gaps", params={"rank": "class", "resource": "lng"}).json()
    for it in body["items"][:3]:
        summ = client.get(f"/taxons/{it['taxid']}").json()
        assert it["n_rows"] == summ["n_rows"]
        res = summ["resources"]["lng"]
        assert it["covered"] == res["covered"]
        assert it["percent"] == res["percent"]
        assert it["gap"] == summ["n_rows"] - res["covered"]


def test_gaps_limit_honoured(client):
    body = client.get("/gaps", params={"rank": "class", "resource": "lng", "limit": 1}).json()
    assert body["returned"] <= 1


def test_gaps_unknown_root_404(client):
    assert client.get("/gaps", params={"root": 99999999}).status_code == 404


def test_gaps_invalid_params_422(client):
    assert client.get("/gaps", params={"rank": "domain"}).status_code == 422
    assert client.get("/gaps", params={"resource": "xyz"}).status_code == 422


def test_gaps_is_cacheable(client):
    r = client.get("/gaps")
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")


def _stats_dict(stats: list[dict]) -> dict[str, float | None]:
    return {s["key"]: s["value"] for s in stats}


def test_gaps_quality_stats_shape(client):
    """By default each item carries the quality of the data it *does* have: one
    entry per QUALITY_STATS key (from /config), each float-or-null."""
    keys = {q["key"] for q in client.get("/config").json()["quality_stats"]}
    assert keys  # the quality dimension is configured
    body = client.get("/gaps", params={"rank": "class", "resource": "lng"}).json()
    assert body["items"]
    for it in body["items"]:
        stats = _stats_dict(it["stats"])
        assert set(stats) == keys
        for v in stats.values():
            assert v is None or isinstance(v, (int, float))


def test_gaps_include_quality_false_omits_stats(client):
    """The lightweight path (used by the landing teaser) returns empty stats."""
    body = client.get(
        "/gaps", params={"rank": "class", "resource": "lng", "include_quality": "false"}
    ).json()
    assert body["items"]
    assert all(it["stats"] == [] for it in body["items"])


def test_gaps_quality_matches_the_taxon(client):
    """A gap clade's quality stats are the stats ``/taxons/{taxid}`` serves."""
    body = client.get("/gaps", params={"rank": "class", "resource": "lng"}).json()
    it = body["items"][0]  # Mammalia on both slice and prod
    taxon = client.get(f"/taxons/{it['taxid']}").json()
    assert _stats_dict(it["stats"]) == _stats_dict(taxon["stats"])
