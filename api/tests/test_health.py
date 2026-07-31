"""Tests for the liveness (/health) and readiness (/health/ready) endpoints."""

from __future__ import annotations


def test_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_ok(client):
    # The `client` fixture only runs with the serving Postgres reachable, so
    # readiness must report the DB as ok here.
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "ok"}
