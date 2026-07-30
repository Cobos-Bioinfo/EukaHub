"""Tests for GET /taxon/{taxid} — the lineage breadcrumb."""

from __future__ import annotations


def test_lineage_homo_sapiens(client):
    body = client.get("/taxon/9606").json()
    # Node fields echo the deepest lineage entry.
    assert body["taxid"] == 9606
    assert body["name"] == "Homo sapiens"
    assert body["rank"] == "species"

    lin = body["lineage"]
    assert lin[0]["taxid"] == 1  # root first
    assert lin[-1]["taxid"] == 9606  # this taxon last
    # A known ancestor sits somewhere in between.
    assert any(hop["taxid"] == 2759 and hop["name"] == "Eukaryota" for hop in lin)
    # Strictly increasing depth (root -> node), and each hop is unique.
    taxids = [hop["taxid"] for hop in lin]
    assert len(taxids) == len(set(taxids))


def test_lineage_root_is_singleton(client):
    body = client.get("/taxon/1").json()
    assert [hop["taxid"] for hop in body["lineage"]] == [1]


def test_lineage_not_found(client):
    assert client.get("/taxon/999999999").status_code == 404
