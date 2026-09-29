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
