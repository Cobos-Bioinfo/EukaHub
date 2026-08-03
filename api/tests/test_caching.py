"""Cache-Control on GET responses: cacheable data endpoints, uncached health.

The dataset is read-only between offline rebuilds, so successful GETs advertise
a public max-age; health/readiness must never be cached.
"""

from __future__ import annotations


def test_summary_is_cacheable(client):
    r = client.get("/clade/2759/summary")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "public" in cc and "max-age=" in cc


def test_breakdown_is_cacheable(client):
    r = client.get("/clade/2759/breakdown", params={"rank": "phylum", "limit": 1})
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")


def test_metrics_config_is_cacheable(client):
    r = client.get("/metrics-config")
    assert "public" in r.headers.get("cache-control", "")


def test_health_is_not_cached(client):
    assert client.get("/health").headers.get("cache-control") == "no-store"


def test_readiness_is_not_cached(client):
    assert client.get("/health/ready").headers.get("cache-control") == "no-store"


# --- ETag / conditional requests -------------------------------------------


def test_json_get_has_etag(client):
    """A cacheable JSON GET advertises a (weak) ETag over its body."""
    r = client.get("/metrics-config")
    etag = r.headers.get("etag")
    assert etag and etag.startswith('W/"')
    assert int(r.headers["content-length"]) == len(r.content)  # unchanged by ETag


def test_matching_if_none_match_returns_304(client):
    """Revalidating with the current ETag yields a bodyless 304 that keeps the
    ETag and Cache-Control, so the client's cached copy is reused."""
    etag = client.get("/metrics-config").headers["etag"]
    r = client.get("/metrics-config", headers={"If-None-Match": etag})
    assert r.status_code == 304
    assert r.content == b""
    assert r.headers.get("etag") == etag
    assert "public" in r.headers.get("cache-control", "")


def test_wildcard_if_none_match_returns_304(client):
    r = client.get("/metrics-config", headers={"If-None-Match": "*"})
    assert r.status_code == 304


def test_stale_if_none_match_returns_full_body(client):
    """A non-matching ETag serves the full 200 body (normal cache miss)."""
    r = client.get("/metrics-config", headers={"If-None-Match": 'W/"stale"'})
    assert r.status_code == 200
    assert len(r.content) > 0


def test_etag_matches_across_identical_requests(client):
    """The ETag is a stable content fingerprint: identical requests share it."""
    assert client.get("/gaps").headers["etag"] == client.get("/gaps").headers["etag"]


def test_streamed_export_has_no_etag(client):
    """The streamed TSV export is not buffered/fingerprinted (only JSON is)."""
    r = client.get("/clade/2759/export.tsv", params={"rank": "phylum"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/tab-separated-values")
    assert "etag" not in r.headers


def test_health_has_no_etag(client):
    assert "etag" not in client.get("/health").headers
