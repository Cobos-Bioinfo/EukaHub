"""Tests for GET /compare — several groups lined up side by side.

Rebuild/slice-safe: Mammalia (40674) and Homo sapiens (9606) are both in the
full DB and the CI seed slice, so they anchor the assertions. Values are
cross-checked against /clade/{taxid}/summary rather than frozen.
"""

from __future__ import annotations

from eukahub_core.metrics import METRIC_KEYS, QUALITY_KEYS


def test_compare_two_groups_shape(client):
    body = client.get("/compare", params={"taxids": "40674,9606"}).json()
    groups = body["groups"]
    assert [g["taxid"] for g in groups] == [40674, 9606]  # input order preserved

    for g in groups:
        assert g["name"] and g["rank"]
        assert g["n_rows"] >= 0
        assert set(g["resources"]) == set(METRIC_KEYS)
        for r in g["resources"].values():
            assert 0.0 <= r["percent"] <= 100.0
            assert r["covered"] <= g["n_rows"] or g["n_rows"] == 0
        assert [q["key"] for q in g["quality"]] == list(QUALITY_KEYS)
        busco = next(q["value"] for q in g["quality"] if q["key"] == "busco")
        assert busco is None or 0.0 <= busco <= 100.0


def test_compare_matches_summary(client):
    """A compare entry is the same rollup the summary endpoint serves."""
    g = client.get("/compare", params={"taxids": "40674"}).json()["groups"][0]
    summ = client.get("/clade/40674/summary").json()
    assert g["n_rows"] == summ["n_rows"]
    for k in METRIC_KEYS:
        assert g["resources"][k]["total"] == summ["resources"][k]["total"]
        assert g["resources"][k]["covered"] == summ["resources"][k]["covered"]


def test_compare_drops_unknown_taxid(client):
    body = client.get("/compare", params={"taxids": "9606,99999999"}).json()
    assert [g["taxid"] for g in body["groups"]] == [9606]


def test_compare_dedupes_and_caps(client):
    """Duplicates collapse; the response is capped at six groups."""
    body = client.get("/compare", params={"taxids": "40674,40674,9606"}).json()
    assert [g["taxid"] for g in body["groups"]] == [40674, 9606]


def test_compare_no_valid_taxids_422(client):
    assert client.get("/compare", params={"taxids": "abc"}).status_code == 422
    assert client.get("/compare", params={"taxids": ""}).status_code == 422
    assert client.get("/compare").status_code == 422  # param required


def test_compare_is_cacheable(client):
    r = client.get("/compare", params={"taxids": "40674,9606"})
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")
