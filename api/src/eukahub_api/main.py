"""EukaHub API: read-only serving of the genomic-resource dataset.

The application itself: CORS, the middleware every response goes through
(``middleware``), the error responses (``errors``) and the resources, mapped in
``router``. Every request is logged as one structured JSON line (see
``logging_config``).
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eukahub_api import errors
from eukahub_api.db import lifespan as db_lifespan
from eukahub_api.logging_config import configure_logging
from eukahub_api.middleware import add_response_headers, log_requests
from eukahub_api.router import router
from eukahub_api.settings import get_settings

log = logging.getLogger("eukahub.api")

# CORS: the SPA calls /api same-origin via the nginx/Vite proxy, so browsers
# don't hit the API cross-origin in normal use. This allowlist is for direct
# API consumers / alternate origins — set CORS_ALLOW_ORIGINS (comma-separated)
# per deploy; the default covers local dev + the prod web container.
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:8080"

# Clients reach the API at /api/v1 through a proxy (Vite in dev, nginx in prod)
# that strips the prefix, as Annotrieve serves /api/v0. Setting root_path tells
# FastAPI its external mount point so the docs at `/api/v1/docs` reference
# `/api/v1/openapi.json` correctly. Override with API_ROOT_PATH="" to serve the
# docs when hitting uvicorn directly.
_ROOT_PATH = os.environ.get("API_ROOT_PATH", "/api/v1")


def cors_allow_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", _DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure structured logging, read the deployment settings (so any warning
    about them is logged at startup), then open the DB pool (see db.lifespan)."""
    configure_logging()
    get_settings()
    async with db_lifespan(app):
        log.info("startup complete")
        yield


app = FastAPI(
    title="EukaHub API",
    version="0.1.0",
    lifespan=lifespan,
    root_path=_ROOT_PATH,
    exception_handlers=errors.HANDLERS,
)

# Read-only public API: allow cross-origin GETs from the configured origins; no
# credentials (no cookies/auth), so the allowlist stays an explicit set.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
    allow_credentials=False,
)
# Added in this order, so log_requests is the outermost layer and times everything.
app.middleware("http")(add_response_headers)
app.middleware("http")(log_requests)

app.include_router(router)


def openapi() -> dict[str, Any]:
    """FastAPI's OpenAPI document, with the error responses as problem details."""
    if app.openapi_schema is None:
        app.openapi_schema = errors.document(FastAPI.openapi(app))
    return app.openapi_schema


app.openapi = openapi
