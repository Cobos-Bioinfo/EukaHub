"""``/assemblies``: genome assemblies, optionally under a taxon."""

from typing import Annotated

from fastapi import APIRouter, Query

from eukahub_api.db import Conn
from eukahub_api.params import Cursor, Within, within_path
from eukahub_api.queries import AssemblySort, SortOrder, list_records
from eukahub_api.schemas import AssemblyPage, AssemblyRecord

router = APIRouter()


@router.get("/assemblies", response_model=AssemblyPage)
def assemblies(
    conn: Conn,
    within: Within = None,
    sort_by: AssemblySort = AssemblySort.release_date,
    sort_order: SortOrder = SortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Cursor = None,
) -> AssemblyPage:
    """Genome assemblies, newest first by default; records missing the sort field
    come last. The quality stats of a taxon's assemblies are in ``/taxons/{taxid}/stats``."""
    total, result = list_records(
        conn, source="assembly", within_path=within_path(conn, within), sort=sort_by.value,
        descending=sort_order is SortOrder.desc, limit=limit, cursor=cursor,
    )
    return AssemblyPage(
        total=total, limit=limit, next=result.next, previous=result.previous,
        results=[AssemblyRecord(**r) for r in result.rows],
    )
