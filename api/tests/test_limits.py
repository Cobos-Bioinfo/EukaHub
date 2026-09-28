"""Tests for the server-protection limits: the per-query statement timeout and
the pool-exhaustion fallback.

The deploy target is a one-core host, so a request that needs minutes of CPU
must be cut off by Postgres itself, and the client must get a clear, uncached
error instead of a 500 or a truncated download.
"""

from __future__ import annotations

import psycopg
from eukahub_api import main
from eukahub_api.db import statement_timeout_ms
from psycopg.errors import QueryCanceled
from psycopg_pool import PoolTimeout


def _slow_query(conn: psycopg.Connection, taxid: int):
    """Stand-in for a too-expensive query: a real statement that Postgres
    cancels at a (lowered) statement timeout."""
    conn.execute("SET LOCAL statement_timeout = 50")
    conn.execute("SELECT pg_sleep(2)")
    raise AssertionError("statement_timeout did not fire")


def test_api_connections_carry_the_statement_timeout(client):
    with main.app.state.pool.connection() as conn:
        (setting,) = conn.execute(
            "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'"
        ).fetchone()
    assert int(setting) == statement_timeout_ms()


def test_cancelled_query_is_a_clean_504(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_summary", _slow_query)
    resp = client.get("/clade/2759/summary")
    assert resp.status_code == 504
    assert "smaller group" in resp.json()["detail"]
    # Errors must never be cached by the browser or the nginx proxy cache.
    assert "public" not in resp.headers.get("cache-control", "")
    # The cancelled connection went back to the pool usable.
    assert client.get("/health/ready").status_code == 200


def test_export_timeout_fails_before_the_download_starts(client, monkeypatch):
    def _cancelled_export(pool, **kwargs):
        yield "header\n"
        raise QueryCanceled("canceling statement due to statement timeout")

    monkeypatch.setattr(main, "iter_export_tsv", _cancelled_export)
    resp = client.get("/clade/2759/export.tsv?rank=species")
    assert resp.status_code == 504
    assert resp.headers["content-type"].startswith("application/json")


def test_pool_exhaustion_is_a_retryable_503(client, monkeypatch):
    def _no_connection(conn, taxid):
        raise PoolTimeout("couldn't get a connection after 30.00 sec")

    monkeypatch.setattr(main, "fetch_summary", _no_connection)
    resp = client.get("/clade/2759/summary")
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "10"
    assert "public" not in resp.headers.get("cache-control", "")
