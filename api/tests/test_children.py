"""Tests for GET /taxon/{taxid}/children — the tree lazy-expand endpoint.

Exercises the live Phase-1 DB (via the shared `client` fixture), so the taxonomy
facts asserted here (Eukaryota's children, Homo sapiens' childless subspecies)
are stable NCBI taxonomy, matching the style of test_lineage.py.
"""

from __future__ import annotations


def test_children_root_sorted_by_species(client):
    """Eukaryota's direct children come back sorted by species count desc, each
    carrying the tree fields (resources + has_children)."""
    d = client.get("/taxon/2759/children", params={"limit": 5}).json()
    assert d["parent"]["taxid"] == 2759
    assert d["parent"]["name"] == "Eukaryota"
    assert d["total"] >= 20  # ~21 direct children of Eukaryota
    assert d["returned"] == 5

    counts = [i["n_rows"] for i in d["items"]]
    assert counts == sorted(counts, reverse=True)  # non-increasing
    assert d["items"][0]["name"] == "Opisthokonta"  # most species-rich child

    top = d["items"][0]
    assert top["has_children"] is True
    assert set(top["resources"]) == {"ass", "ann", "rna", "lng"}


def test_children_pagination(client):
    """total is the pre-paging count; limit/offset return disjoint slices."""
    page1 = client.get("/taxon/2759/children", params={"limit": 5, "offset": 0}).json()
    page2 = client.get("/taxon/2759/children", params={"limit": 5, "offset": 5}).json()

    assert page1["total"] == page2["total"]  # stable across pages
    ids1 = {i["taxid"] for i in page1["items"]}
    ids2 = {i["taxid"] for i in page2["items"]}
    assert len(ids1) == 5 and len(ids2) == 5
    assert ids1.isdisjoint(ids2)


def test_children_sort_param_changes_order(client):
    """A different sort keeps the same child set but reorders it by that metric."""
    by_species = client.get("/taxon/2759/children", params={"limit": 25}).json()
    by_ann = client.get(
        "/taxon/2759/children", params={"limit": 25, "sort": "c_ann"}
    ).json()

    assert {i["taxid"] for i in by_species["items"]} == {
        i["taxid"] for i in by_ann["items"]
    }
    ann_counts = [i["resources"]["ann"]["covered"] for i in by_ann["items"]]
    assert ann_counts == sorted(ann_counts, reverse=True)


def test_children_leaf_returns_empty(client):
    """A childless taxon returns an empty list (not a 404), and its parent's
    has_children flag agrees. Homo sapiens' subspecies are the childless case."""
    kids = client.get("/taxon/9606/children").json()["items"]
    leaves = [k for k in kids if not k["has_children"]]
    assert leaves, "expected a childless child of Homo sapiens"

    res = client.get(f"/taxon/{leaves[0]['taxid']}/children").json()
    assert res["total"] == 0
    assert res["returned"] == 0
    assert res["items"] == []


def test_children_infraspecific_flag(client):
    """A species' children are below-species (is_infraspecific True); a genus'
    children are species (False). One probe on the parent settles the page."""
    sub = client.get("/taxon/9606/children").json()["items"]  # Homo sapiens' subspecies
    assert sub and all(i["is_infraspecific"] for i in sub)

    genus_kids = client.get("/taxon/9605/children").json()["items"]  # Homo (genus) -> species
    assert genus_kids and not any(i["is_infraspecific"] for i in genus_kids)


def test_children_not_found(client):
    """An unknown taxid is a 404, distinct from 'present but childless'."""
    assert client.get("/taxon/999999999/children").status_code == 404
