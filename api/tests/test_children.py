"""A taxon's children: GET /taxons?parent=..., the tree's lazy expansion.

The taxonomy facts asserted here (Eukaryota's children, Homo sapiens' childless
subspecies) are stable NCBI taxonomy.
"""

from __future__ import annotations

import psycopg
import pytest
from eukahub_api.db import database_url
from eukahub_core.metrics import METRIC_NAMES


def _children(client, taxid: int, **params) -> dict:
    response = client.get("/taxons", params={"parent": taxid, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_children_root_sorted_by_species(client):
    d = _children(client, 2759, limit=5)
    assert d["total"] >= 20  # ~21 direct children of Eukaryota
    assert len(d["results"]) == 5
    counts = [i["species"] for i in d["results"]]
    assert counts == sorted(counts, reverse=True)
    top = d["results"][0]
    assert top["name"] == "Opisthokonta"  # most species-rich child
    assert top["has_children"] is True
    assert list(top["resources"]) == list(METRIC_NAMES)


def test_children_pages_cover_every_child_once(client):
    total = _children(client, 2759, limit=1)["total"]
    seen, cursor = [], None
    while True:
        page = _children(client, 2759, limit=5, **({"cursor": cursor} if cursor else {}))
        seen += [i["taxid"] for i in page["results"]]
        cursor = page["next"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == total


def test_children_sort_param_changes_order(client):
    by_species = _children(client, 2759, limit=25)
    by_ann = _children(client, 2759, limit=25, sort_by="resources.annotations.covered")
    assert {i["taxid"] for i in by_species["results"]} == {i["taxid"] for i in by_ann["results"]}
    ann = [i["resources"]["annotations"]["covered"] for i in by_ann["results"]]
    assert ann == sorted(ann, reverse=True)
    by_name = _children(client, 2759, limit=25, sort_by="name", sort_order="asc")
    names = [i["name"] for i in by_name["results"]]
    with psycopg.connect(database_url()) as conn:  # names sort in the database's collation
        (in_order,) = conn.execute(
            "SELECT array_agg(n ORDER BY n) FROM unnest(%s::text[]) n", (names,)
        ).fetchone()
    assert names == in_order


def test_children_leaf_returns_empty(client):
    """A childless taxon has an empty list, not a 404; its has_children agrees."""
    kids = _children(client, 9606)["results"]
    leaves = [k for k in kids if not k["has_children"]]
    assert leaves, "expected a childless child of Homo sapiens"
    res = _children(client, leaves[0]["taxid"])
    assert res["total"] == 0 and res["results"] == [] and res["next"] is None


def test_children_infraspecific_flag(client):
    """A species' children are below-species; a genus' children are species."""
    sub = _children(client, 9606)["results"]  # Homo sapiens' subspecies
    assert sub and all(i["is_infraspecific"] for i in sub)
    genus_kids = _children(client, 9605)["results"]  # Homo (genus) -> species
    assert genus_kids and not any(i["is_infraspecific"] for i in genus_kids)


def test_children_of_informal_species_are_infraspecific(client):
    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "SELECT p.taxid FROM taxon p WHERE p.rank = 'informal species' "
            "AND EXISTS (SELECT 1 FROM taxon c WHERE c.parent_id = p.taxid) LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("no informal species with finer taxa in this dataset")
    items = _children(client, row[0])["results"]
    assert items and all(i["is_infraspecific"] for i in items)


def test_children_of_an_unknown_taxon_is_a_404(client):
    assert client.get("/taxons", params={"parent": 999999999}).status_code == 404
