"""Shared fixtures for the API tests.

The endpoint tests exercise the full stack against the docker-compose Postgres
(the Phase 1 dataset). The ``client`` fixture skips any test that requests it
when the DB isn't reachable, so DB-free tests (e.g. schema guards) still run.

Run with the stack up:  uv run --package eukahub-api pytest api/tests
"""

from __future__ import annotations

import psycopg
import pytest
from eukahub_api.db import database_url
from eukahub_api.main import app
from fastapi.testclient import TestClient


def _db_available() -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=3):
            return True
    except Exception:  # noqa: BLE001  (any connection failure means "skip")
        return False


@pytest.fixture(scope="session")
def client():
    """A TestClient with the connection pool open (via lifespan). Skips the
    requesting test if the serving Postgres isn't reachable."""
    if not _db_available():
        pytest.skip("serving Postgres not reachable")
    with TestClient(app) as c:
        yield c
