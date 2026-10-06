"""``/annotations``: gene annotations, optionally under a taxon."""

from typing import Annotated

from fastapi import APIRouter, Query

from eukahub_api.db import Conn
from eukahub_api.params import Cursor, Within, within_path
from eukahub_api.queries import AnnotationSort, SortOrder, list_records
from eukahub_api.schemas import AnnotationPage, AnnotationRecord

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
