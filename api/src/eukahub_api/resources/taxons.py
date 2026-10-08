"""``/taxons`` and its sub-resources: taxa with their counts, their quality stats,
a TSV report, sets of clades, and one taxon with its ancestors and stats."""

import itertools
from typing import Annotated

import psycopg
from eukahub_core.metrics import QUALITY_STATS
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from eukahub_api.clade_sets import clade_set, set_metadata, set_pieces, taxon_refs
from eukahub_api.db import Conn
from eukahub_api.pagination import Page
from eukahub_api.params import Cursor, Within, within_path
from eukahub_api.queries import (
    MAX_PAGE,
    METRIC_KEY_OF,
    FilterLogic,
    MetricFilter,
    SortOrder,
    TargetRank,
    TaxonFilter,
    TaxonListRow,
    TaxonSort,
    fetch_ancestors,
    fetch_quality_for_taxids,
    fetch_root,
    fetch_set_quality,
    fetch_set_taxa,
    fetch_taxon,
    fetch_taxon_stats,
    iter_report_tsv,
    list_taxa,
)
from eukahub_api.schemas import (
    MAX_CLADES_PER_GROUP,
    Aggregate,
    AggregatePage,
    AssemblyComposition,
    CladeSummary,
    ResourceSummary,
    Taxon,
    TaxonPage,
    TaxonStats,
    TaxonStatsPage,
)
from eukahub_api.settings import get_settings

router = APIRouter()

# Most taxids one /taxons request may name.
MAX_TAXIDS = 100


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
    within: Within = None,
    rank: Annotated[TargetRank | None, Query(description="Only taxa of this rank.")] = None,
    taxids: Annotated[
        str | None,
        Query(description=f"Only these taxa: comma-separated taxids, at most {MAX_TAXIDS}."),
    ] = None,
    filter: Annotated[
        list[MetricFilter] | None,
        Query(description="Only taxa with data for these resources (their names in /config)."),
    ] = None,
    logic: Annotated[
        FilterLogic, Query(description="Whether `filter` needs every resource (`and`) or any (`or`).")
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
        within_path(conn, parent)
    return TaxonFilter(
        q=q,
        fuzzy=fuzzy,
        parent=parent,
        within=within,
        within_path=within_path(conn, within),
        rank=rank.value if rank else None,
        taxids=_parse_taxids(taxids, "taxids", MAX_TAXIDS) if taxids is not None else (),
        filter_keys=[METRIC_KEY_OF[f.value] for f in filter or ()],
        logic=logic,
        exclude_empty=exclude_empty,
    )


_TaxonFilter = Annotated[TaxonFilter, Depends(taxon_filter)]
_TaxonSortBy = Annotated[
    TaxonSort | None,
    Query(
        description="The path of a number in a taxon: `species`, "
        "`resources.<resource>.covered`, `.missing` or `.total`, or `composition.<field>`; "
        "or `name`. Without it: relevance for `q`, else `species`."
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
    return list_taxa(
        conn,
        f,
        sort=sort_by.value if sort_by else None,
        descending=sort_order is SortOrder.desc,
        limit=limit,
        cursor=cursor,
    )


@router.get("/taxons", response_model=TaxonPage)
def taxons(
    conn: Conn,
    f: _TaxonFilter,
    sort_by: _TaxonSortBy = None,
    sort_order: SortOrder = SortOrder.desc,
    limit: _Limit = 25,
    cursor: Cursor = None,
) -> TaxonPage:
    """Taxa with their counts: a name search (``q``), a taxon's children
    (``parent``), every taxon of a rank under a taxon (``within`` and ``rank``), or
    chosen taxa (``taxids``), narrowed by the data they have. Sort by
    ``resources.<resource>.missing`` for the groups with the most species still
    missing it. Their quality stats are in ``/taxons/stats``."""
    total, result = _taxa_page(conn, f, sort_by, sort_order, limit, cursor)
    return TaxonPage(
        total=total,
        limit=limit,
        next=result.next,
        previous=result.previous,
        results=list(map(_taxon, result.rows)),
    )


@router.get("/taxons/stats", response_model=TaxonStatsPage)
def taxons_stats(
    conn: Conn,
    f: _TaxonFilter,
    sort_by: _TaxonSortBy = None,
    sort_order: SortOrder = SortOrder.desc,
    limit: _Limit = 25,
    cursor: Cursor = None,
) -> TaxonStatsPage:
    """The quality stats (best BUSCO, median genes, genome size and N50) of the taxa
    ``/taxons`` lists for the same parameters, page for page and with the same
    cursors, each over the records on or below the taxon. Computed at build time,
    so a page costs about what the same page of ``/taxons`` does."""
    total, result = _taxa_page(conn, f, sort_by, sort_order, limit, cursor)
    quality = fetch_quality_for_taxids(conn, [r.meta.taxid for r in result.rows])
    return TaxonStatsPage(
        total=total,
        limit=limit,
        next=result.next,
        previous=result.previous,
        results=[
            TaxonStats(taxid=r.meta.taxid, name=r.name, stats=quality[r.meta.taxid])
            for r in result.rows
        ],
    )


@router.get("/taxons/report")
def taxons_report(
    conn: Conn,
    request: Request,
    f: _TaxonFilter,
    sort_by: _TaxonSortBy = None,
    sort_order: SortOrder = SortOrder.desc,
) -> StreamingResponse:
    """Every taxon ``/taxons`` lists for the same filters and sort, as a streamed
    TSV download: taxid, name, species count, then the species with each resource
    and the total of each resource. Not cached: a report runs to tens of MB, and
    nginx's cache is kept for the small responses the interface repeats."""
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
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/taxons/aggregates", response_model=AggregatePage)
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
        include=taxon_refs((t for t in inc if marks.get(t) is True), taxa),
        exclude=taxon_refs((t for t in exc if marks.get(t) is False), taxa),
        species=meta.n_rows,
        resources=ResourceSummary.by_metric(meta),
        composition=AssemblyComposition.from_metadata(meta),
        stats={q.key: quality[q.key] for q in QUALITY_STATS},
    )
    return AggregatePage(total=1, limit=1, next=None, previous=None, results=[aggregate])


@router.get("/taxons/{taxid}", response_model=Taxon)
def taxon(taxid: int, conn: Conn) -> Taxon:
    """One taxon, the same object ``/taxons`` lists: species count, per-resource
    coverage and assembly composition. A species, an informal species or a finer
    taxon also has ``direct``: its records attached to the taxon itself rather than
    to a finer taxon below it."""
    return _taxon(fetch_taxon(conn, taxid))


@router.get("/taxons/{taxid}/ancestors", response_model=list[Taxon])
def taxon_ancestors(taxid: int, conn: Conn) -> list[Taxon]:
    """The root, every taxon below it down to this one, and this one, in that order,
    as the same objects ``/taxons`` lists. The whole lineage, unpaged: it is at
    most a few dozen taxa."""
    return list(map(_taxon, fetch_ancestors(conn, taxid)))


@router.get("/taxons/{taxid}/stats", response_model=TaxonStats)
def taxon_stats(taxid: int, conn: Conn) -> TaxonStats:
    """The quality stats (best BUSCO, median genes, genome size and N50) of the
    records on or below one taxon, the same object ``/taxons/stats`` lists,
    computed at build time."""
    name, stats = fetch_taxon_stats(conn, taxid)
    return TaxonStats(taxid=taxid, name=name, stats=stats)
