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
    # '%' is escaped to match literally. Search is scoped to Eukaryota, where no
    # name contains a literal '%'. Unescaped, '%' would be the match-all wildcard
    # and return a full page of names; escaped, it matches nothing — pinning both
    # the escaping and the eukaryote scope.
    body = client.get("/search", params={"q": "%", "limit": 50}).json()
    assert body == []


def test_search_excludes_non_eukaryotes(client):
    # Escherichia coli (Bacteria, taxid 562) lies outside the eukaryotic subtree,
    # so it must never surface in the root picker.
    body = client.get("/search", params={"q": "Escherichia coli", "limit": 50}).json()
    assert all(hit["taxid"] != 562 for hit in body)


def test_search_no_matches_is_empty(client):
    body = client.get("/search", params={"q": "zzzznotarealtaxonzzzz"}).json()
    assert body == []


def test_search_requires_query(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422
