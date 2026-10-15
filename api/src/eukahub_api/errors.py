"""The error responses. Every error is problem details (RFC 9457), whether the API,
FastAPI or Starlette raised it, and the OpenAPI document says so."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.errors import QueryCanceled
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException

from eukahub_api.pagination import InvalidCursor
from eukahub_api.queries import TaxonNotFound
from eukahub_api.schemas import ParameterError, Problem

log = logging.getLogger("eukahub.api")

MEDIA_TYPE = "application/problem+json"

# Every route's error response, for the OpenAPI document (see ``document``).
RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": Problem, "description": "An error, as problem details (RFC 9457)."}
}


def problem(
    status: int,
    detail: str,
    *,
    errors: list[ParameterError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = Problem(title=HTTPStatus(status).phrase, status=status, detail=detail, errors=errors)
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        headers=headers,
        media_type=MEDIA_TYPE,
    )


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """An HTTPException from a resource, or Starlette's own 404 and 405 (with Allow)."""
    return problem(exc.status_code, str(exc.detail), headers=exc.headers)


async def invalid_parameters(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's checks of the query and path parameters, and unknown parameters
    (see ``params.only_known_parameters``)."""
    errors = [
        ParameterError(
            parameter=str(e["loc"][1] if len(e["loc"]) > 1 else e["loc"][0]), detail=e["msg"]
        )
        for e in exc.errors()
    ]
    detail = "; ".join(f"{e.parameter}: {e.detail}" for e in errors)
    return problem(422, detail, errors=errors)


async def taxon_not_found(request: Request, exc: TaxonNotFound) -> JSONResponse:
    return problem(404, str(exc))


async def invalid_cursor(request: Request, exc: InvalidCursor) -> JSONResponse:
    return problem(
        422, f"cursor: {exc}", errors=[ParameterError(parameter="cursor", detail=str(exc))]
    )


async def query_timed_out(request: Request, exc: QueryCanceled) -> JSONResponse:
    """A query hit the statement timeout (see ``db.statement_timeout_ms``) and
    Postgres cancelled it. Retrying won't help, so say what will."""
    log.warning("query cancelled", extra={"path": request.url.path, "error": str(exc)})
    return problem(
        504,
        "This request needs more work than the server allows per query. "
        "Try a smaller group or a coarser rank.",
    )


async def pool_exhausted(request: Request, exc: PoolTimeout) -> JSONResponse:
    """Every pooled connection stayed busy for the pool's whole wait: the
    server is saturated. Transient, so ask the client to retry."""
    log.warning("connection pool exhausted", extra={"path": request.url.path})
    return problem(503, "The server is busy. Please retry shortly.", headers={"Retry-After": "10"})


async def internal_error(request: Request, exc: Exception) -> JSONResponse:
    """Anything unexpected. Starlette re-raises the exception after this answers, so
    the server still logs its traceback."""
    return problem(500, "Something went wrong on the server. Please try again later.")


HANDLERS = {
    HTTPException: http_error,
    RequestValidationError: invalid_parameters,
    TaxonNotFound: taxon_not_found,
    InvalidCursor: invalid_cursor,
    QueryCanceled: query_timed_out,
    PoolTimeout: pool_exhausted,
    Exception: internal_error,
}


def document(schema: dict[str, Any]) -> dict[str, Any]:
    """File each operation's error response under ``application/problem+json``, the
    type ``problem`` sends: FastAPI files a response model under the route's own
    media type."""
    for operation in (op for path in schema["paths"].values() for op in path.values()):
        content = operation["responses"]["default"]["content"]
        if "application/json" in content:
            content[MEDIA_TYPE] = content.pop("application/json")
    return schema
