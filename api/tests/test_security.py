"""Tests for baseline security headers and the CORS allowlist.

CORS origins come from CORS_ALLOW_ORIGINS (default includes localhost:5173),
so these assert against that default without setting env.
"""

from __future__ import annotations

ALLOWED_ORIGIN = "http://localhost:5173"


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_cors_allows_configured_origin(client):
    r = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_cors_omits_unknown_origin(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_preflight(client):
    r = client.options(
        "/clade/2759/summary",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "GET" in r.headers.get("access-control-allow-methods", "")
