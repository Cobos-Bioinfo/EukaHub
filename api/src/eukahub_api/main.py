"""EukaHub API — read-only serving of the genomic-resource dataset.

Resources:

- ``GET /config``                      — what a client reads once: dataset stamp, measure
  chrome, deployment links and groups.
- ``GET /taxons``                      — taxa by name, parent, rank under a taxon or taxid,
  with their counts; sorted, filtered and paged.
- ``GET /taxons/stats``                — the quality stats of the same taxa, page for page.
- ``GET /taxons/report``               — every taxon the same list would page through, as TSV.
- ``GET /taxons/aggregates``           — data for a set of clades (include minus exclude).
- ``GET /taxons/{taxid}``              — one taxon, the same object ``/taxons`` lists.
- ``GET /taxons/{taxid}/ancestors``    — the root down to the taxon, as taxa.
- ``GET /taxons/{taxid}/stats``        — the quality stats of one taxon.
- ``GET /assemblies``                  — genome assemblies, optionally under a taxon.
- ``GET /annotations``                 — gene annotations, optionally under a taxon.

Lists page with an opaque cursor (see ``pagination``). ``/health`` (liveness) and
``/health/ready`` (DB readiness) round out the service. Every request is logged as
one structured JSON line (see ``logging_config``).
"""

import hashlib
import itertools
import logging
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Annotated

import psycopg
from eukahub_core.metrics import METRICS, QUALITY_STATS
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg.errors import QueryCanceled
from psycopg_pool import PoolTimeout

from eukahub_api.clade_sets import SetTaxon, clade_set, resolve_groups, set_metadata, set_pieces
from eukahub_api.db import Conn
from eukahub_api.db import lifespan as db_lifespan
from eukahub_api.logging_config import configure_logging
from eukahub_api.pagination import InvalidCursor, Page
from eukahub_api.queries import (
    MAX_PAGE,
    AnnotationSort,
    AssemblySort,
    FilterLogic,
    MetricFilter,
    SortOrder,
    TargetRank,
    TaxonFilter,
    TaxonListRow,
    TaxonNotFound,
    TaxonSort,
    fetch_ancestors,
    fetch_dataset_meta,
    fetch_quality_for_taxids,
    fetch_root,
    fetch_set_quality,
    fetch_set_taxa,
    fetch_taxon,
    fetch_taxon_stats,
    iter_report_tsv,
    list_records,
    list_taxa,
)
from eukahub_api.schemas import (
    MAX_CLADES_PER_GROUP,
    Aggregate,
    AggregatePage,
    AnnotationPage,
    AnnotationRecord,
    AppConfig,
    AssemblyComposition,
    AssemblyPage,
    AssemblyRecord,
    CladeSummary,
    CustomGroup,
    CustomGroupItem,
    DatasetMeta,
    MetricConfig,
    QualityStatConfig,
    QualityStatValue,
    ResourceSummary,
    Taxon,
    TaxonPage,
    TaxonRef,
    TaxonStats,
    TaxonStatsPage,
)
from eukahub_api.settings import get_settings

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


def _etag_of(body: bytes) -> str:
    """A weak ETag over the exact response bytes. md5 is a content fingerprint
    here (not a security primitive); weak so downstream transforms (gzip) don't
    invalidate the match, which is the semantics we want for a whole-body tag."""
    return f'W/"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'


def _if_none_match(header: str | None, etag: str) -> bool:
    """RFC 7232 If-None-Match test (weak comparison): ``*`` matches anything,
    otherwise the client's list must contain our tag, ignoring the ``W/`` prefix."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    norm = etag.removeprefix("W/").strip()
    return any(t.strip().removeprefix("W/").strip() == norm for t in header.split(","))

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
    """Configure structured logging, read the deployment settings (so any warning
    about them is logged at startup), then open the DB pool (see db.lifespan)."""
    configure_logging()
    get_settings()
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
    """Baseline security headers on every response, plus Cache-Control and an
    ETag on cacheable GETs (setdefault so a handler that set its own keeps
    precedence). A matching If-None-Match short-circuits to a bodyless 304."""
    response = await call_next(request)
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Caching applies to GET (the routes are GET-only — a HEAD gets 405, which is
    # never cached, so `curl -I` shows a reverse-proxy MISS; test the cache with a
    # real GET).
    if request.method != "GET":
        return response
    # Health must stay fresh; other successful GETs are cacheable until rebuild.
    if request.url.path.startswith("/health"):
        response.headers.setdefault("Cache-Control", "no-store")
        return response
    if response.status_code != 200:
        return response
    response.headers.setdefault("Cache-Control", f"public, max-age={_CACHE_MAX_AGE}")
    # ETag + conditional requests for materialized JSON. The middleware runs over
    # a streaming wrapper (BaseHTTPMiddleware), so buffer the body to fingerprint
    # it — cheap for these small JSON payloads. The streamed TSV export
    # (text/tab-separated-values) is left untouched. A revalidating client that
    # already holds this exact body gets a bodyless 304.
    if not response.headers.get("content-type", "").startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    etag = _etag_of(body)
    response.headers.setdefault("ETag", etag)
    headers = dict(response.headers)
    headers.pop("content-length", None)  # recomputed from the body / empty 304
    if _if_none_match(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, status_code=response.status_code, headers=headers)


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


@app.exception_handler(QueryCanceled)
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


@app.exception_handler(PoolTimeout)
async def pool_exhausted(request: Request, exc: PoolTimeout) -> JSONResponse:
    """Every pooled connection stayed busy for the pool's whole wait: the
    server is saturated. Transient, so ask the client to retry."""
    log.warning("connection pool exhausted", extra={"path": request.url.path})
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "10"},
        content={"detail": "The server is busy. Please retry shortly."},
    )


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


@app.get("/config", response_model=AppConfig)
def config(conn: Conn) -> AppConfig:
    """What a client reads once before showing any data: the dataset being served
    (``built_at`` is ``null`` before the first build has stamped the database), the
    presentation of each measure and quality stat, and the deployment's links,
    Wikipedia summary endpoint, curated groups and custom groups. Pass a custom
    group's clades to ``/taxons/aggregates`` for its data."""
    settings = get_settings()
    row = fetch_dataset_meta(conn)
    dataset = (
        DatasetMeta(
            built_at=None, taxon_count=0, assembly_count=0, annotation_count=0, clade_count=0
        )
        if row is None
        else DatasetMeta(
            built_at=row[0],
            taxon_count=row[1],
            assembly_count=row[2],
            annotation_count=row[3],
            clade_count=row[4],
        )
    )
    return AppConfig(
        dataset=dataset,
        metrics=[MetricConfig.from_metric(m, settings.link_templates[m.key]) for m in METRICS],
        quality_stats=[QualityStatConfig.from_stat(q) for q in QUALITY_STATS],
        feedback_url=settings.feedback_url,
        source_code_url=settings.source_code_url,
        privacy_contact_email=settings.privacy_contact_email,
        wikipedia_summary_url=settings.wikipedia_summary_url,
        groups=list(settings.groups),
        custom_groups=_custom_groups(conn, settings.custom_groups),
    )


def _custom_groups(
    conn: psycopg.Connection, groups: Sequence[CustomGroup]
) -> list[CustomGroupItem]:
    """The custom groups that fit the current taxonomy, each with its clades. A
    group that doesn't fit is left out and logged."""
    if not groups:
        return []
    order = dict.fromkeys(t for g in groups for t in g.include + g.exclude)
    taxa = fetch_set_taxa(conn, order)
    return [
        CustomGroupItem(
            id=r.group.id,
            label=r.group.label,
            parent=r.group.parent,
            rest=r.group.rest,
            include=_taxon_refs((t for t in order if r.marks.get(t) is True), taxa),
            exclude=_taxon_refs((t for t in order if r.marks.get(t) is False), taxa),
        )
        for r in resolve_groups(groups, taxa)
    ]


def _parse_taxids(raw: str, name: str, cap: int) -> list[int]:
    """The distinct taxids in a comma-separated list, or a 422 naming the problem.
    Stops at the first taxid over the cap, so a long list costs nothing."""
    ids: dict[int, None] = {}
    for part in filter(None, (p.strip() for p in raw.split(","))):
        if not (part.isascii() and part.isdigit() and len(part) <= 10):
            raise HTTPException(status_code=422, detail=f"{name}: {part!r} is not a taxid")
        ids[int(part)] = None
        if len(ids) > cap:
            raise HTTPException(status_code=422, detail=f"{name}: at most {cap} taxids")
    return list(ids)


def _taxon_refs(taxids: Iterable[int], taxa: Mapping[int, SetTaxon]) -> list[TaxonRef]:
    return [TaxonRef(taxid=t, name=taxa[t].name, rank=taxa[t].rank) for t in taxids]


def _within_path(conn: psycopg.Connection, taxid: int | None) -> str | None:
    """The path of the ``within`` taxon, or a 404 when it is unknown."""
    if taxid is None:
        return None
    try:
        return fetch_root(conn, taxid)[2]
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")


_Within = Annotated[
    int | None,
    Query(description="Only rows on this taxon or below it (e.g. 40674 for mammals)."),
]
_Cursor = Annotated[
    str | None,
    Query(
        max_length=1000,
        description="``next`` or ``previous`` from a page with the same sort, for the "
        "page after or before it.",
    ),
]


def _list_records(conn: psycopg.Connection, source: str, **kwargs) -> tuple[int, Page[dict]]:
    try:
        return list_records(conn, source=source, **kwargs)
    except InvalidCursor as e:
        raise HTTPException(status_code=422, detail=f"cursor: {e}")


# Most taxids one /taxons request may name.
MAX_TAXIDS = 100


def taxon_filter(
    conn: Conn,
    q: Annotated[
        str | None,
        Query(
            min_length=3,
            max_length=100,
            description="Only taxa whose name contains this text, ignoring case (or is "
            "spelled like it, with `fuzzy`). The root and 'cellular organisms' are left out.",
        ),
    ] = None,
    fuzzy: Annotated[
        bool, Query(description="Match `q` by spelling instead, for a misspelt name.")
    ] = False,
    parent: Annotated[
        int | None, Query(description="Only the direct children of this taxon.")
    ] = None,
    within: _Within = None,
    rank: Annotated[TargetRank | None, Query(description="Only taxa of this rank.")] = None,
    taxids: Annotated[
        str | None,
        Query(description=f"Only these taxa: comma-separated taxids, at most {MAX_TAXIDS}."),
    ] = None,
    filter: Annotated[
        list[MetricFilter] | None,
        Query(description="Only taxa with data for these resources."),
    ] = None,
    logic: Annotated[
        FilterLogic, Query(description="Whether `filter` needs every resource (AND) or any (OR).")
    ] = FilterLogic.AND,
    exclude_empty: Annotated[
        bool, Query(description="Only taxa with data for at least one resource.")
    ] = False,
) -> TaxonFilter:
    """The /taxons filters, checked: an unknown ``parent`` or ``within`` taxon is a
    404, anything malformed a 422."""
    if q is not None and "\x00" in q:
        raise HTTPException(status_code=422, detail="q: contains a NUL character")
    if fuzzy and q is None:
        raise HTTPException(status_code=422, detail="fuzzy: needs q")
    if parent is not None:
        _within_path(conn, parent)
    return TaxonFilter(
        q=q,
        fuzzy=fuzzy,
        parent=parent,
        within=within,
        within_path=_within_path(conn, within),
        rank=rank.value if rank else None,
        taxids=_parse_taxids(taxids, "taxids", MAX_TAXIDS) if taxids is not None else (),
        filter_keys=[f.value for f in filter or ()],
        logic=logic,
        exclude_empty=exclude_empty,
    )


_TaxonFilter = Annotated[TaxonFilter, Depends(taxon_filter)]
_TaxonSortBy = Annotated[
    TaxonSort | None,
    Query(
        description="A count column, `gap_<resource>` (species without that resource) or "
        "`name`. Without it: relevance for `q`, else species count (`n_rows`)."
    ),
]


_Limit = Annotated[int, Query(ge=1, le=MAX_PAGE)]


def _taxon(r: TaxonListRow) -> Taxon:
    summary = CladeSummary.from_metadata(r.name, r.rank, r.meta, r.is_infraspecific)
    summary.direct = r.direct
    return Taxon(**summary.model_dump(), context=r.context, has_children=r.has_children)


def _taxa_page(
    conn: psycopg.Connection,
    f: TaxonFilter,
    sort_by: TaxonSort | None,
    sort_order: SortOrder,
    limit: int,
    cursor: str | None,
) -> tuple[int, Page[TaxonListRow]]:
    try:
        return list_taxa(
            conn,
            f,
            sort=sort_by.value if sort_by else None,
            descending=sort_order is SortOrder.desc,
            limit=limit,
            cursor=cursor,
        )
    except InvalidCursor as e:
        raise HTTPException(status_code=422, detail=f"cursor: {e}")


@app.get("/taxons", response_model=TaxonPage)
def taxons(
    conn: Conn,
    f: _TaxonFilter,
    sort_by: _TaxonSortBy = None,
    sort_order: SortOrder = SortOrder.desc,
    limit: _Limit = 25,
    cursor: _Cursor = None,
) -> TaxonPage:
    """Taxa with their counts: a name search (``q``), a taxon's children
    (``parent``), every taxon of a rank under a taxon (``within`` and ``rank``), or
    chosen taxa (``taxids``), narrowed by the data they have. Sort by
    ``gap_<resource>`` for the groups with the most species still missing it. Their
    quality stats are in ``/taxons/stats``."""
    total, result = _taxa_page(conn, f, sort_by, sort_order, limit, cursor)
    return TaxonPage(
        total=total,
        limit=limit,
        next=result.next,
        previous=result.previous,
        results=list(map(_taxon, result.rows)),
    )


@app.get("/taxons/stats", response_model=TaxonStatsPage)
def taxons_stats(
    conn: Conn,
    f: _TaxonFilter,
    sort_by: _TaxonSortBy = None,
    sort_order: SortOrder = SortOrder.desc,
    limit: _Limit = 25,
    cursor: _Cursor = None,
) -> TaxonStatsPage:
    """The quality stats (best BUSCO, median genes, genome size and N50) of the taxa
    ``/taxons`` lists for the same parameters, page for page and with the same
    cursors, each computed from the records on or below the taxon. Slower than
    ``/taxons``: about half a second for any page on the full dataset."""
    total, result = _taxa_page(conn, f, sort_by, sort_order, limit, cursor)
    quality = fetch_quality_for_taxids(conn, [r.meta.taxid for r in result.rows])
    return TaxonStatsPage(
        total=total,
        limit=limit,
        next=result.next,
        previous=result.previous,
        results=[
            TaxonStats(
                taxid=r.meta.taxid,
                name=r.name,
                stats=[
                    QualityStatValue(key=k, value=v) for k, v in quality[r.meta.taxid].items()
                ],
            )
            for r in result.rows
        ],
    )


@app.get("/taxons/report")
def taxons_report(
    conn: Conn,
    request: Request,
    f: _TaxonFilter,
    sort_by: _TaxonSortBy = None,
    sort_order: SortOrder = SortOrder.desc,
) -> StreamingResponse:
    """Every taxon ``/taxons`` lists for the same filters and sort, as a streamed
    TSV download: taxid, name, species count, then the species with each resource
    and the total of each resource."""
    rows = iter_report_tsv(
        request.app.state.pool,
        f,
        sort=sort_by.value if sort_by else None,
        descending=sort_order is SortOrder.desc,
        batch_rows=get_settings().export_batch_rows,
    )
    # Pull the header and first batch of rows now: that runs the query (its sort
    # is the expensive part) before any byte is sent, so a statement timeout on a
    # huge report is a clean 504 instead of a 200 that stops mid-download.
    head = list(itertools.islice(rows, 2))
    name = fetch_root(conn, f.within)[0] if f.within is not None else "taxa"
    filename = f"{name.replace(' ', '_')}_{f.rank or 'all'}_data.tsv"
    return StreamingResponse(
        itertools.chain(head, rows),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/taxons/aggregates", response_model=AggregatePage)
def aggregate(
    conn: Conn,
    include: Annotated[
        str, Query(description="Comma-separated taxids of the clades to add up (1-20, e.g. 7742).")
    ],
    exclude: Annotated[
        str,
        Query(description="Comma-separated taxids of clades inside them to leave out (e.g. 32523)."),
    ] = "",
) -> AggregatePage:
    """Species count, per-resource coverage and quality stats for a set of clades:
    the clades in ``include`` minus the clades inside them in ``exclude`` (e.g.
    fish as Vertebrata minus Tetrapoda). A clade inside an excluded one can be
    included again. Counts are sums and differences of the clades' rollups;
    quality stats are computed from the records in the set. A list, like every
    collection, holding the one set asked for."""
    inc = _parse_taxids(include, "include", MAX_CLADES_PER_GROUP)
    exc = _parse_taxids(exclude, "exclude", MAX_CLADES_PER_GROUP)
    if not inc:
        raise HTTPException(status_code=422, detail="include: at least one taxid")
    if set(inc) & set(exc):
        raise HTTPException(status_code=422, detail="a taxid cannot be both included and excluded")
    taxa = fetch_set_taxa(conn, inc + exc)
    marks = clade_set(inc, exc, taxa)
    if isinstance(marks, str):
        raise HTTPException(status_code=422, detail=marks)
    path = {t: ".".join(map(str, taxa[t].path)) for t in marks}
    quality = fetch_set_quality(
        conn,
        [(path[i], [path[o] for o in outside]) for i, outside in set_pieces(marks, taxa)],
    )
    meta = set_metadata(marks, taxa)
    aggregate = Aggregate(
        include=_taxon_refs((t for t in inc if marks.get(t) is True), taxa),
        exclude=_taxon_refs((t for t in exc if marks.get(t) is False), taxa),
        n_rows=meta.n_rows,
        resources=ResourceSummary.by_metric(meta),
        composition=AssemblyComposition.from_metadata(meta),
        stats=[QualityStatValue(key=q.key, value=quality[q.key]) for q in QUALITY_STATS],
    )
    return AggregatePage(total=1, limit=1, next=None, previous=None, results=[aggregate])


@app.get("/taxons/{taxid}", response_model=Taxon)
def taxon(taxid: int, conn: Conn) -> Taxon:
    """One taxon, the same object ``/taxons`` lists: species count, per-resource
    coverage and assembly composition. A species, an informal species or a finer
    taxon also has ``direct``: its records attached to the taxon itself rather than
    to a finer taxon below it."""
    try:
        return _taxon(fetch_taxon(conn, taxid))
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")


@app.get("/taxons/{taxid}/ancestors", response_model=TaxonPage)
def taxon_ancestors(taxid: int, conn: Conn) -> TaxonPage:
    """The root, every taxon below it down to this one, and this one, in that order,
    as the same objects ``/taxons`` lists. One page: a lineage is at most a few
    dozen taxa."""
    try:
        rows = fetch_ancestors(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")
    return TaxonPage(
        total=len(rows), limit=len(rows), next=None, previous=None, results=list(map(_taxon, rows))
    )


@app.get("/taxons/{taxid}/stats", response_model=TaxonStats)
def taxon_stats(taxid: int, conn: Conn) -> TaxonStats:
    """The quality stats (best BUSCO, median genes, genome size and N50) of the
    records on or below one taxon, the same object ``/taxons/stats`` lists. From a
    few milliseconds for a genus to about 0.3 s for Eukaryota."""
    try:
        name, stats = fetch_taxon_stats(conn, taxid)
    except TaxonNotFound:
        raise HTTPException(status_code=404, detail=f"taxon {taxid} not found")
    return TaxonStats(
        taxid=taxid, name=name, stats=[QualityStatValue(key=k, value=v) for k, v in stats.items()]
    )


@app.get("/assemblies", response_model=AssemblyPage)
def assemblies(
    conn: Conn,
    within: _Within = None,
    sort_by: AssemblySort = AssemblySort.release_date,
    sort_order: SortOrder = SortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: _Cursor = None,
) -> AssemblyPage:
    """Genome assemblies, newest first by default; records missing the sort field
    come last. The quality stats of a taxon's assemblies are in ``/taxons/{taxid}``."""
    total, result = _list_records(
        conn, "assembly", within_path=_within_path(conn, within), sort=sort_by.value,
        descending=sort_order is SortOrder.desc, limit=limit, cursor=cursor,
    )
    return AssemblyPage(
        total=total, limit=limit, next=result.next, previous=result.previous,
        results=[AssemblyRecord(**r) for r in result.rows],
    )


@app.get("/annotations", response_model=AnnotationPage)
def annotations(
    conn: Conn,
    within: _Within = None,
    sort_by: AnnotationSort = AnnotationSort.busco_complete,
    sort_order: SortOrder = SortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: _Cursor = None,
) -> AnnotationPage:
    """Gene annotations, best BUSCO first by default; records missing the sort field
    come last. The quality stats of a taxon's annotations are in ``/taxons/{taxid}``."""
    total, result = _list_records(
        conn, "annotation", within_path=_within_path(conn, within), sort=sort_by.value,
        descending=sort_order is SortOrder.desc, limit=limit, cursor=cursor,
    )
    return AnnotationPage(
        total=total, limit=limit, next=result.next, previous=result.previous,
        results=[AnnotationRecord(**r) for r in result.rows],
    )
