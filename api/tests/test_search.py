"""Tests for GET /search — name search for the root picker."""

from __future__ import annotations


def test_search_finds_species(client):
    body = client.get("/search", params={"q": "Homo sapiens"}).json()
    assert any(hit["taxid"] == 9606 and hit["rank"] == "species" for hit in body)


def test_search_is_case_insensitive_and_substring(client):
    body = client.get("/search", params={"q": "homo"}).json()
    assert body
    assert all("homo" in hit["name"].lower() for hit in body)


def test_search_prefix_matches_rank_first(client):
    body = client.get("/search", params={"q": "homo", "limit": 50}).json()
    # Ordering puts names that *start* with the query ahead of mid-string hits.
    assert body[0]["name"].lower().startswith("homo")


def test_search_puts_the_exact_name_first(client):
    body = client.get("/search", params={"q": "homo sapiens", "limit": 50}).json()
    assert body[0]["taxid"] == 9606


def test_search_hits_name_their_nearest_major_rank(client):
    body = client.get("/search", params={"q": "Homo", "limit": 5}).json()
    for hit in body:
        lineage = client.get(f"/taxon/{hit['taxid']}").json()["lineage"]
        above = [a for a in lineage[:-1] if a["rank"] in ("class", "phylum", "kingdom")]
        assert hit["context"] == (above[-1]["name"] if above else None)


def test_search_data_flag_matches_the_summary(client):
    body = client.get("/search", params={"q": "Homo", "limit": 5}).json()
    for hit in body:
        summary = client.get(f"/clade/{hit['taxid']}/summary").json()
        totals = [r["total"] for r in summary["resources"].values()]
        assert hit["has_data"] == any(t > 0 for t in totals)
        assert hit["similar"] is False


def test_search_suggests_close_spellings_when_nothing_matches(client):
    body = client.get("/search", params={"q": "Homo sapeins"}).json()
    assert body[0]["taxid"] == 9606
    assert all(hit["similar"] for hit in body)


def test_search_respects_limit(client):
    body = client.get("/search", params={"q": "homo", "limit": 2}).json()
    assert len(body) == 2


def test_search_escapes_wildcards(client):
    # Unescaped, '%%%' would match every name; no taxon name contains a literal '%'.
    body = client.get("/search", params={"q": "%%%", "limit": 50}).json()
    assert body == []


def test_search_hides_the_spine_above_eukaryota(client):
    for q in ("cellular organisms", "root"):
        body = client.get("/search", params={"q": q, "limit": 50}).json()
        assert all(hit["taxid"] not in (1, 131567) for hit in body)


def test_search_no_matches_is_empty(client):
    body = client.get("/search", params={"q": "zzzznotarealtaxonzzzz"}).json()
    assert body == []


def test_search_requires_query(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422
    assert client.get("/search", params={"q": "ho"}).status_code == 422


def test_search_rejects_a_nul_character(client):
    assert client.get("/search", params={"q": "homo\x00"}).status_code == 422
