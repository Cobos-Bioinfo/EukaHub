"""EukaHub API — read-only serving of the genomic-resource dataset.

Phase 2 read endpoints:

- ``GET /clade/{taxid}/summary``    — the Genomic Resource Summary (Q1).
- ``GET /clade/{taxid}/breakdown``  — descendants at a target rank (Q2).
- ``GET /clade/{taxid}/export.tsv`` — the full breakdown as a TSV download.
- ``GET /taxon/{taxid}``            — the root→node lineage breadcrumb.
- ``GET /taxon/{taxid}/children``   — direct children for the interactive tree.
- ``GET /taxon/{taxid}/about``      — Wikipedia "About" summary (decorative).
- ``GET /search``                   — name search for the root picker.

``/health`` (liveness) + ``/health/ready`` (DB readiness) and ``/metrics-config``
round out the service. Every request is logged as one structured JSON line (see
``logging_config``).
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

from eukahub_core.metrics import METRICS
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from eukahub_api.db import Conn
from eukahub_api.db import lifespan as db_lifespan
from eukahub_api.logging_config import configure_logging
from eukahub_api.queries import (
    FilterLogic,
    MetricFilter,
    SortColumn,
    TargetRank,
    TaxonNotFound,
    fetch_breakdown,
    fetch_children,
    fetch_lineage,
    fetch_root,
    fetch_summary,
    iter_export_tsv,
    search_taxa,
)
from eukahub_api.schemas import (
    Breakdown,
    CladeSummary,
    MetricConfig,
    TaxonAbout,
    TaxonChildren,
    TaxonLineage,
    TaxonNode,
    TaxonRef,
)
from eukahub_api.wikipedia import fetch_about

log = logging.getLogger("eukahub.api")

# CORS: the SPA calls /api same-origin via the nginx/Vite proxy, so browsers
# don't hit the API cross-origin in normal use. This allowlist is for direct
# API consumers / alternate origins — set CORS_ALLOW_ORIGINS (comma-separated)
# per deploy; the default covers local dev + the prod web container.
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:8080"

# Baseline security headers on every API response (defense-in-depth; nginx sets
# its own on the static SPA it serves). HSTS/CSP belong with the TLS terminator.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

# The dataset is read-only and rebuilt offline, so a GET response is valid until
# the next rebuild — safe to cache downstream (browser / CDN / reverse proxy).
# Tune CACHE_MAX_AGE (seconds) to the rebuild cadence; health stays uncached.
_CACHE_MAX_AGE = int(os.environ.get("CACHE_MAX_AGE", "3600"))

# The SPA reaches the API through a proxy (Vite in dev, nginx in prod) that
# strips a `/api` prefix. Setting root_path tells FastAPI its external mount
# point so the docs at `/api/docs` reference `/api/openapi.json` correctly.
# Override with API_ROOT_PATH="" to serve the docs when hitting uvicorn directly.
_ROOT_PATH = os.environ.get("API_ROOT_PATH", "/api")


def cors_allow_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", _DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure structured logging, then open the DB pool (see db.lifespan)."""
    configure_logging()
    async with db_lifespan(app):
        log.info("startup complete")
        yield


app = FastAPI(title="EukaHub API", version="0.1.0", lifespan=lifespan, root_path=_ROOT_PATH)

# Read-only public API: allow cross-origin GETs from the configured origins; no
# credentials (no cookies/auth), so the allowlist stays an explicit set.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.middleware("http")
async def add_response_headers(request: Request, call_next):
    """Baseline security headers on every response, plus Cache-Control on
    cacheable GETs (setdefault so a handler that set its own keeps precedence)."""
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Health must stay fresh; other successful GETs are cacheable until rebuild.
    if request.method == "GET":
        if request.url.path.startswith("/health"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif response.status_code == 200:
            response.headers.setdefault(
                "Cache-Control", f"public, max-age={_CACHE_MAX_AGE}"
            )
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One structured log line per request. Health probes drop to DEBUG so they
    don't flood the log at the default INFO level."""
    start = time.perf_counter()
    response = await call_next(request)
    level = logging.DEBUG if request.url.path.startswith("/health") else logging.INFO
    log.log(
        level,
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up and serving. Checks no dependencies, so a
    container/orchestrator can tell 'process alive' apart from 'DB ready'."""
    return {"status": "ok"}


@app.get("/health/ready")
def readiness(request: Request, response: Response) -> dict[str, str]:
    """Readiness: can we actually serve reads? Pings Postgres with SELECT 1 and
    returns 503 if it's unreachable, so a load balancer holds traffic until the
    read-only serving DB is back."""
    try:
        with request.app.state.pool.connection() as conn:
            conn.execute("SELECT 1")
    # Any failure — DB down, pool timeout, unexpected error — means "not ready".
    except Exception:
        log.warning("readiness check failed", exc_info=True)
        response.status_code = 503
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ready", "database": "ok"}


@app.get("/metrics-config", response_model=list[MetricConfig])
def metrics_config() -> list[MetricConfig]:
    """The tracked metrics — static card chrome the frontend renders once,
    keyed by the same metric keys the per-clade payloads use."""
    return [MetricConfig.from_metric(m) for m in METRICS]


@app.get("/clade/{taxid}/summary", response_model=CladeSummary)
def clade_summary(taxid: int, conn: Conn) -> CladeSummary:
    """Genomic Resource Summary for one taxon: species count + per-resource
    coverage/total/percent. One indexed lookup on `clade_features`."""
    try:
        name, rank, meta = fetch_summary(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")
    return CladeSummary.from_metadata(name, rank, meta)


@app.get("/clade/{taxid}/breakdown", response_model=Breakdown)
def clade_breakdown(
    taxid: int,
    conn: Conn,
    rank: Annotated[TargetRank, Query(description="Rank to break the root down by.")],
    sort: SortColumn = SortColumn.n_rows,
    filter: Annotated[
        list[MetricFilter] | None,
        Query(description="Keep only taxa with data for these resource(s)."),
    ] = None,
    logic: FilterLogic = FilterLogic.AND,
    exclude_empty: bool = True,
    limit: Annotated[int, Query(ge=1, le=1000)] = 25,
) -> Breakdown:
    """How a clade's data is distributed at a lower rank (Q2).

    Descendants of `taxid` at `rank`, with filter/sort/limit pushed into a
    single indexed `ltree` query. Defaults mirror Euka-Survey: sort by species
    count, exclude empty taxa, AND-combine filters, top 25.
    """
    filter_keys = [f.value for f in (filter or [])]
    try:
        root_ref, items, total = fetch_breakdown(
            conn,
            root_taxid=taxid,
            rank=rank.value,
            sort=sort.value,
            filter_keys=filter_keys,
            logic=logic,
            exclude_empty=exclude_empty,
            limit=limit,
        )
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")

    root_taxid, root_name, root_rank = root_ref
    return Breakdown(
        root=TaxonRef(taxid=root_taxid, name=root_name, rank=root_rank),
        rank=rank.value,
        total_matches=total,
        returned=len(items),
        items=[CladeSummary.from_metadata(name, rk, meta) for name, rk, meta in items],
    )


@app.get("/taxon/{taxid}", response_model=TaxonLineage)
def taxon_lineage(taxid: int, conn: Conn) -> TaxonLineage:
    """The taxon and its root→node lineage (breadcrumb). One indexed `ltree`
    ancestor query on the materialized path."""
    try:
        rows = fetch_lineage(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")
    lineage = [TaxonRef(taxid=t, name=n, rank=r) for t, n, r in rows]
    node = lineage[-1]  # deepest = the requested taxon
    return TaxonLineage(taxid=node.taxid, name=node.name, rank=node.rank, lineage=lineage)


@app.get("/taxon/{taxid}/children", response_model=TaxonChildren)
def taxon_children(
    taxid: int,
    conn: Conn,
    sort: SortColumn = SortColumn.n_rows,
    limit: Annotated[int, Query(ge=1, le=500)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaxonChildren:
    """A taxon's direct children (adjacency), for lazy-expanding the tree.

    One indexed `parent_id` lookup, sorted by species count by default (biggest
    clades first) and paginated via limit/offset so a node with tens of
    thousands of children loads a screenful at a time. Each child carries a
    `has_children` flag. 404 if the taxid is unknown; a childless taxon (e.g. a
    species leaf) returns an empty list.
    """
    try:
        parent_ref, items, total = fetch_children(
            conn, taxid=taxid, sort=sort.value, limit=limit, offset=offset
        )
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")

    p_taxid, p_name, p_rank = parent_ref
    return TaxonChildren(
        parent=TaxonRef(taxid=p_taxid, name=p_name, rank=p_rank),
        total=total,
        returned=len(items),
        items=[
            TaxonNode.from_child(name, rank, meta, has_children)
            for name, rank, meta, has_children in items
        ],
    )


@app.get("/taxon/{taxid}/about", response_model=TaxonAbout | None)
def taxon_about(taxid: int, conn: Conn) -> TaxonAbout | None:
    """A Wikipedia "About" summary for the taxon — the decorative dashboard card.

    Resolves the taxon's scientific name, then does one cached, server-side GET
    against Wikipedia's REST summary endpoint (so we can send the User-Agent
    Wikipedia's policy wants and cache across viewers). ``404`` if the taxid is
    unknown; otherwise the summary, or ``null`` when there's no usable article —
    the frontend omits the card either way. The ``null`` result caches as a
    normal 200, so taxa without a page don't re-hit the network downstream.
    """
    try:
        name, _rank, _path = fetch_root(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")
    return fetch_about(name)


@app.get("/clade/{taxid}/export.tsv")
def clade_export(
    taxid: int,
    conn: Conn,
    request: Request,
    rank: Annotated[TargetRank, Query(description="Rank to break the root down by.")],
    sort: SortColumn = SortColumn.n_rows,
    filter: Annotated[list[MetricFilter] | None, Query()] = None,
    logic: FilterLogic = FilterLogic.AND,
    exclude_empty: bool = False,
) -> StreamingResponse:
    """The full breakdown at `rank` as a streamed TSV download.

    Same subtree query as `breakdown` but unlimited and streamed via a
    server-side cursor. Defaults to the complete breakdown (empties included);
    pass filter/exclude_empty/sort to export exactly what the table shows.
    """
    # Resolve the root first so a bad taxid is a clean 404 (can't change the
    # status once the stream has started) and to name the download.
    try:
        root_name, _root_rank, root_path = fetch_root(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")

    filter_keys = [f.value for f in (filter or [])]
    rows = iter_export_tsv(
        request.app.state.pool,
        root_path=root_path,
        rank=rank.value,
        sort=sort.value,
        filter_keys=filter_keys,
        logic=logic,
        exclude_empty=exclude_empty,
    )
    filename = f"{root_name.replace(' ', '_')}_{rank.value}_data.tsv"
    return StreamingResponse(
        rows,
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/search", response_model=list[TaxonRef])
def search(
    conn: Conn,
    q: Annotated[str, Query(min_length=1, max_length=100, description="Name query.")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[TaxonRef]:
    """Case-insensitive taxon-name search for the root picker. Substring match,
    prefix-matches first (served by the `pg_trgm` GIN index on `taxon.name`)."""
    return [TaxonRef(taxid=t, name=n, rank=r) for t, n, r in search_taxa(conn, q, limit)]
