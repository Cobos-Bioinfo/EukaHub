"""EukaHub API — read-only serving of the genomic-resource dataset.

Phase 2 read endpoints:

- ``GET /clade/{taxid}/summary``    — the Genomic Resource Summary (Q1).
- ``GET /clade/{taxid}/breakdown``  — descendants at a target rank (Q2).
- ``GET /clade/{taxid}/export.tsv`` — the full breakdown as a TSV download.
- ``GET /taxon/{taxid}``            — the root→node lineage breadcrumb.
- ``GET /search``                   — name search for the root picker.

``/health`` and ``/metrics-config`` remain from the scaffold. Next: generate
OpenAPI + TS types from the metric config for the frontend (Phase 3).
"""

import os
from typing import Annotated

from eukahub_core.metrics import METRICS
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from eukahub_api.db import Conn, lifespan
from eukahub_api.queries import (
    FilterLogic,
    MetricFilter,
    SortColumn,
    TargetRank,
    TaxonNotFound,
    fetch_breakdown,
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
    TaxonLineage,
    TaxonRef,
)

app = FastAPI(title="EukaHub API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "database_configured": "DATABASE_URL" in os.environ}


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
