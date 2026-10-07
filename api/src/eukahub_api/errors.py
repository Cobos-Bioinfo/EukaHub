"""The error responses for exceptions any resource can raise."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from psycopg.errors import QueryCanceled
from psycopg_pool import PoolTimeout

from eukahub_api.pagination import InvalidCursor
from eukahub_api.queries import TaxonNotFound

log = logging.getLogger("eukahub.api")


async def taxon_not_found(request: Request, exc: TaxonNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def invalid_cursor(request: Request, exc: InvalidCursor) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": f"cursor: {exc}"})


async def query_timed_out(request: Request, exc: QueryCanceled) -> JSONResponse:
    """A query hit the statement timeout (see ``db.statement_timeout_ms``) and
    Postgres cancelled it. Retrying won't help, so say what will."""
    log.warning("query cancelled", extra={"path": request.url.path, "error": str(exc)})
    return JSONResponse(
        status_code=504,
        content={
            "detail": "This request needs more work than the server allows per query. "
            "Try a smaller group or a coarser rank."
        },
    )


async def pool_exhausted(request: Request, exc: PoolTimeout) -> JSONResponse:
    """Every pooled connection stayed busy for the pool's whole wait: the
    server is saturated. Transient, so ask the client to retry."""
    log.warning("connection pool exhausted", extra={"path": request.url.path})
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "10"},
        content={"detail": "The server is busy. Please retry shortly."},
    )


HANDLERS = {
    TaxonNotFound: taxon_not_found,
    InvalidCursor: invalid_cursor,
    QueryCanceled: query_timed_out,
    PoolTimeout: pool_exhausted,
}
