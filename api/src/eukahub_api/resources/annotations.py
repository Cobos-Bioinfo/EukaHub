"""``/annotations``: gene annotations, optionally under a taxon."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from eukahub_api.db import Conn
from eukahub_api.downloads import tsv_download
from eukahub_api.params import Cursor, Within, within_path
from eukahub_api.queries import (
    AnnotationSort,
    SortOrder,
    fetch_root,
    iter_records_tsv,
    list_records,
    records_report_sql,
)
from eukahub_api.schemas import AnnotationPage, AnnotationRecord
from eukahub_api.settings import get_settings

router = APIRouter()


@router.get("/annotations", response_model=AnnotationPage)
def annotations(
    conn: Conn,
    within: Within = None,
    sort_by: AnnotationSort = AnnotationSort.busco_complete,
    sort_order: SortOrder = SortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Cursor = None,
) -> AnnotationPage:
    """Gene annotations, best BUSCO first by default; records missing the sort field
    come last. The quality stats of a taxon's annotations are in ``/taxons/{taxid}/stats``."""
    total, result = list_records(
        conn, source="annotation", within_path=within_path(conn, within), sort=sort_by.value,
        descending=sort_order is SortOrder.desc, limit=limit, cursor=cursor,
    )
    return AnnotationPage(
        total=total, limit=limit, next=result.next, previous=result.previous,
        results=[AnnotationRecord(**r) for r in result.rows],
    )


@router.get("/annotations/report")
def annotations_report(
    conn: Conn,
    request: Request,
    within: Within = None,
    sort_by: AnnotationSort = AnnotationSort.busco_complete,
    sort_order: SortOrder = SortOrder.desc,
) -> StreamingResponse:
    """Every annotation ``/annotations`` lists for the same taxon and sort, as a
    streamed TSV download with the record's fields as columns."""
    sql, params, n_keys = records_report_sql(
        "annotation", within_path(conn, within), sort=sort_by.value,
        descending=sort_order is SortOrder.desc,
    )
    rows = iter_records_tsv(
        request.app.state.pool, sql, params, n_keys=n_keys,
        batch_rows=get_settings().export_batch_rows,
    )
    name = fetch_root(conn, within).name if within is not None else "all"
    return tsv_download(rows, f"{name}_annotations.tsv")
