"""Tests for the per-record drill-down endpoints:
``GET /taxon/{taxid}/assemblies`` and ``.../annotations``.

DB-backed via the shared ``client`` fixture; the facts asserted are stable NCBI
biology (Homo sapiens has many assemblies + Ensembl annotations; Mammalia is a
large subtree) plus structural invariants that survive a data rebuild.
"""

from __future__ import annotations


def test_assemblies_human(client):
    """Homo sapiens assemblies: live assembly-quality stats + real records."""
    d = client.get("/taxon/9606/assemblies", params={"limit": 3}).json()
    assert d["root"]["taxid"] == 9606
    assert d["root"]["name"] == "Homo sapiens"
    assert d["total"] > 100  # thousands of human assemblies
    assert d["returned"] == 3

    assert {s["key"] for s in d["stats"]} == {"genome_size", "contig_n50"}
    for s in d["stats"]:
        assert s["value"] is not None and s["value"] > 0  # human has genomes

    it = d["items"][0]
    assert it["assembly_accession"].startswith(("GCA_", "GCF_"))
    assert it["download_url"].endswith("/")  # deep link to the NCBI genome page
    assert isinstance(it["bioprojects"], list)
    assert it["organism"]  # scientific name at the record's taxid


def test_assemblies_pagination_stable_total(client):
    """total is the pre-paging subtree count; limit/offset return disjoint slices."""
    p1 = client.get("/taxon/40674/assemblies", params={"limit": 5, "offset": 0}).json()
    p2 = client.get("/taxon/40674/assemblies", params={"limit": 5, "offset": 5}).json()
    assert p1["total"] == p2["total"] > 5  # Mammalia has many assemblies
    ids1 = {i["assembly_accession"] for i in p1["items"]}
    ids2 = {i["assembly_accession"] for i in p2["items"]}
    assert len(ids1) == 5 and len(ids2) == 5
    assert ids1.isdisjoint(ids2)


def test_annotations_human_busco_sorted(client):
    """Homo sapiens annotations: BUSCO/gene stats, records default-sorted by
    BUSCO desc (best-annotated genomes first)."""
    d = client.get("/taxon/9606/annotations", params={"limit": 5}).json()
    assert d["total"] > 10
    assert {s["key"] for s in d["stats"]} == {"busco", "genes"}

    it = d["items"][0]
    assert it["annotation_id"]
    assert it["source_database"]  # e.g. Ensembl / NCBI
    # default sort = busco_complete DESC NULLS LAST → non-null and non-increasing
    buscos = [i["busco_complete"] for i in d["items"] if i["busco_complete"] is not None]
    assert buscos == sorted(buscos, reverse=True)


def test_records_not_found(client):
    """An unknown taxid is a 404 on both per-record endpoints."""
    assert client.get("/taxon/999999999/assemblies").status_code == 404
    assert client.get("/taxon/999999999/annotations").status_code == 404
