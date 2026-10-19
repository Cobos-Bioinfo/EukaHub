"""Tests for baseline security headers and CORS.

Any site may call the API from the browser unless CORS_ALLOW_ORIGINS narrows it,
so these assert against that default without setting env.
"""

from __future__ import annotations

from eukahub_api.main import cors_allow_origins

OTHER_SITE = "https://example.org"


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_cors_allows_any_origin_without_credentials(client):
    r = client.get("/health", headers={"Origin": OTHER_SITE})
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in r.headers


def test_cors_preflight(client):
    r = client.options(
        "/taxons/2759",
        headers={
            "Origin": OTHER_SITE,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "GET" in r.headers.get("access-control-allow-methods", "")


def test_cors_preflight_refuses_other_methods(client):
    r = client.options(
        "/taxons/2759",
        headers={"Origin": OTHER_SITE, "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 400


def test_cors_origins_from_the_environment(monkeypatch):
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert cors_allow_origins() == ["*"]
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.example, https://b.example,")
    assert cors_allow_origins() == ["https://a.example", "https://b.example"]
