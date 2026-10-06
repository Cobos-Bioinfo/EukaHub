"""Name search: GET /taxons?q=..."""

from __future__ import annotations


def _search(client, q: str, **params) -> list[dict]:
    response = client.get("/taxons", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def test_search_finds_species(client):
    hits = _search(client, "Homo sapiens")
    assert any(h["taxid"] == 9606 and h["rank"] == "species" for h in hits)


def test_search_is_case_insensitive_and_substring(client):
    hits = _search(client, "homo")
    assert hits
    assert all("homo" in h["name"].lower() for h in hits)


def test_search_prefix_matches_rank_first(client):
    assert _search(client, "homo", limit=50)[0]["name"].lower().startswith("homo")


def test_search_puts_the_exact_name_first(client):
    assert _search(client, "homo sapiens", limit=50)[0]["taxid"] == 9606


def test_search_hits_name_their_nearest_major_rank(client):
    for hit in _search(client, "Homo", limit=5):
        lineage = client.get(f"/taxons/{hit['taxid']}/ancestors").json()["results"]
        above = [a for a in lineage[:-1] if a["rank"] in ("class", "phylum", "kingdom")]
        assert hit["context"] == (above[-1]["name"] if above else None)


def test_search_hits_carry_the_taxon_counts(client):
    for hit in _search(client, "Homo", limit=5):
        taxon = client.get(f"/taxons/{hit['taxid']}").json()
        assert hit["resources"] == taxon["resources"]
        assert hit["n_rows"] == taxon["n_rows"]
        assert hit == taxon
        assert "stats" not in hit  # in /taxons/stats


def test_fuzzy_search_finds_close_spellings(client):
    assert _search(client, "Homo sapeins") == []
    assert _search(client, "Homo sapeins", fuzzy="true")[0]["taxid"] == 9606


def test_fuzzy_needs_a_query(client):
    assert client.get("/taxons", params={"fuzzy": "true"}).status_code == 422


def test_search_respects_limit_and_pages(client):
    first = client.get("/taxons", params={"q": "homo", "limit": 2}).json()
    assert len(first["results"]) == 2 and first["total"] > 2
    second = client.get(
        "/taxons", params={"q": "homo", "limit": 2, "cursor": first["next"]}
    ).json()
    assert {h["taxid"] for h in first["results"]}.isdisjoint(h["taxid"] for h in second["results"])
    # A cursor of one query does not carry over to another.
    other = client.get("/taxons", params={"q": "homi", "limit": 2, "cursor": first["next"]})
    assert other.status_code == 422


def test_search_escapes_wildcards(client):
    # Unescaped, '%%%' would match every name; no taxon name contains a literal '%'.
    assert _search(client, "%%%", limit=50) == []


def test_search_hides_the_spine_above_eukaryota(client):
    for q in ("cellular organisms", "root"):
        assert all(h["taxid"] not in (1, 131567) for h in _search(client, q, limit=50))


def test_search_no_matches_is_empty(client):
    body = client.get("/taxons", params={"q": "zzzznotarealtaxonzzzz"}).json()
    assert body["results"] == [] and body["total"] == 0 and body["next"] is None


def test_search_query_length(client):
    assert client.get("/taxons", params={"q": ""}).status_code == 422
    assert client.get("/taxons", params={"q": "ho"}).status_code == 422
    assert client.get("/taxons", params={"q": "h" * 101}).status_code == 422


def test_search_rejects_a_nul_character(client):
    assert client.get("/taxons", params={"q": "homo\x00"}).status_code == 422
