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
    body = client.get("/search", params={"q": "a", "limit": 5}).json()
    assert len(body) <= 5


def test_search_escapes_wildcards(client):
    # '%' is escaped to match literally: every hit contains a literal '%'
    # (some NCBI names do). Unescaped, '%' is the match-all wildcard and would
    # return names *without* a '%', so this pins the escaping.
    body = client.get("/search", params={"q": "%"}).json()
    assert body, "expected some names containing a literal '%'"
    assert all("%" in hit["name"] for hit in body)


def test_search_no_matches_is_empty(client):
    body = client.get("/search", params={"q": "zzzznotarealtaxonzzzz"}).json()
    assert body == []


def test_search_requires_query(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422
