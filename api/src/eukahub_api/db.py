"""Postgres connection pool + FastAPI wiring for the read-only serving path.

Serving is read-only and low-write-never, so a small pooled set of
connections is all we need. The pool is opened once at app startup (via the
lifespan context manager) and handed out per-request through the ``Conn``
dependency. Endpoints stay ``def`` (sync) — FastAPI runs them in a
threadpool, which pairs naturally with psycopg's sync pool.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Request
from psycopg_pool import ConnectionPool

# Matches the pipeline's DEFAULT_DB_URL so local dev talks to the same
# docker-compose Postgres. docker-compose overrides this via DATABASE_URL.
DEFAULT_DATABASE_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the connection pool for the app's lifetime, close it on shutdown."""
    with ConnectionPool(database_url(), min_size=1, max_size=8, open=False) as pool:
        app.state.pool = pool
        yield


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    """Per-request connection, returned to the pool when the request ends."""
    with request.app.state.pool.connection() as conn:
        yield conn


# Annotate endpoint params with this to receive a pooled connection.
Conn = Annotated[psycopg.Connection, Depends(get_conn)]
