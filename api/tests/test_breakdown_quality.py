"""Tests for GET /clade/{taxid}/breakdown/quality against the live DB.

The per-bucket quality lenses of the "data map". Asserts rebuild-safe
invariants (shape, key set, bucket ↔ breakdown correspondence, value types)
rather than exact numbers.
"""

from __future__ import annotations

from eukahub_core.metrics import QUALITY_KEYS


def test_breakdown_quality_shape(client):
    body = client.get("/clade/40674/breakdown/quality?rank=order").json()
    assert isinstance(body, list)
    assert body, "Mammalia should have orders carrying records"
    for bucket in body:
        assert set(bucket) == {"taxid", "stats"}
        keys = [s["key"] for s in bucket["stats"]]
        # Every bucket reports every quality stat, in QUALITY_STATS order.
        assert keys == list(QUALITY_KEYS)
        for s in bucket["stats"]:
            assert s["value"] is None or isinstance(s["value"], (int, float))


def test_breakdown_quality_buckets_are_breakdown_taxa(client):
    """Every quality bucket is a rank-`rank` taxon under the root (i.e. a tile)."""
    rank = "order"
    quality = client.get(f"/clade/40674/breakdown/quality?rank={rank}").json()
    bd = client.get(f"/clade/40674/breakdown?rank={rank}&exclude_empty=false&limit=1000").json()
    tile_taxids = {it["taxid"] for it in bd["items"]}
    for bucket in quality:
        assert bucket["taxid"] in tile_taxids


def test_breakdown_quality_busco_in_range(client):
    body = client.get("/clade/40674/breakdown/quality?rank=order").json()
    for bucket in body:
        busco = next(s["value"] for s in bucket["stats"] if s["key"] == "busco")
        assert busco is None or 0.0 <= busco <= 100.0


def test_breakdown_quality_invalid_rank_422(client):
    assert client.get("/clade/40674/breakdown/quality?rank=kingdom").status_code == 422


def test_breakdown_quality_missing_rank_422(client):
    assert client.get("/clade/40674/breakdown/quality").status_code == 422


def test_breakdown_quality_bad_root_404(client):
    assert client.get("/clade/999999999/breakdown/quality?rank=order").status_code == 404
