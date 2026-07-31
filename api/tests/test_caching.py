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
