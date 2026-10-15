"""``/assemblies``: genome assemblies, optionally under a taxon."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from eukahub_api.db import Conn
from eukahub_api.downloads import tsv_download
from eukahub_api.params import Cursor, Within, within_path
from eukahub_api.queries import (
    AssemblyFilter,
    AssemblyLevel,
    AssemblySort,
    SortOrder,
    assemblies_report_sql,
    fetch_root,
    iter_records_tsv,
    list_assemblies,
)
from eukahub_api.schemas import AssemblyPage, AssemblyRecord
from eukahub_api.settings import get_settings

router = APIRouter()


def assembly_filter(
    conn: Conn,
    within: Within = None,
    assembly_level: Annotated[
        list[AssemblyLevel] | None,
        Query(description="Only assemblies at these levels (any of them)."),
    ] = None,
    reference: Annotated[
        bool, Query(description="Only the assemblies NCBI marks as reference genomes.")
    ] = False,
    ebp_standard: Annotated[
        bool,
        Query(
            description="Only assemblies with the contiguity of the Earth BioGenome Project's "
            "reference standard: contig N50 of 1 Mb or more and scaffold N50 of 10 Mb or more."
        ),
    ] = False,
    min_contig_n50: Annotated[
        int | None, Query(ge=0, le=10**12, description="Only assemblies with at least this contig N50 (bp).")
    ] = None,
    best_per_species: Annotated[
        bool,
        Query(
            description="Only the best assembly of each species, the first in the recommended "
            "order among those the other filters keep. Subspecies and strains count with "
            "their species (`species_taxid`)."
        ),
    ] = False,
) -> AssemblyFilter:
    """The /assemblies filters; an unknown ``within`` taxon is a 404."""
    return AssemblyFilter(
        within=within,
        within_path=within_path(conn, within),
        levels=tuple(level.value for level in assembly_level or ()),
        reference=reference,
        ebp_standard=ebp_standard,
        min_contig_n50=min_contig_n50,
        best_per_species=best_per_species,
    )


_AssemblyFilter = Annotated[AssemblyFilter, Depends(assembly_filter)]
_SortBy = Annotated[
    AssemblySort,
    Query(
        description="`recommended`: reference genomes first, then the most complete level, "
        "then the longest contig N50. Or a field of the record; records missing it come last."
    ),
]


@router.get("/assemblies", response_model=AssemblyPage)
def assemblies(
    conn: Conn,
    f: _AssemblyFilter,
    sort_by: _SortBy = AssemblySort.recommended,
    sort_order: SortOrder = SortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Cursor = None,
) -> AssemblyPage:
    """Genome assemblies, recommended first by default. ``total`` counts species
    with ``best_per_species``. The quality stats of a taxon's assemblies are in
    ``/taxons/{taxid}/stats``."""
    total, result = list_assemblies(
        conn, f, sort=sort_by.value, descending=sort_order is SortOrder.desc, limit=limit,
        cursor=cursor,
    )
    return AssemblyPage(
        total=total, limit=limit, next=result.next, previous=result.previous,
        results=[AssemblyRecord(**r) for r in result.rows],
    )


@router.get("/assemblies/report")
def assemblies_report(
    conn: Conn,
    request: Request,
    f: _AssemblyFilter,
    sort_by: _SortBy = AssemblySort.recommended,
    sort_order: SortOrder = SortOrder.desc,
) -> StreamingResponse:
    """Every assembly ``/assemblies`` lists for the same filters and sort, as a
    streamed TSV download with the record's fields as columns."""
    sql, params, n_keys = assemblies_report_sql(
        f, sort=sort_by.value, descending=sort_order is SortOrder.desc
    )
    rows = iter_records_tsv(
        request.app.state.pool, sql, params, n_keys=n_keys,
        batch_rows=get_settings().export_batch_rows,
    )
    name = fetch_root(conn, f.within)[0] if f.within is not None else "all"
    return tsv_download(rows, f"{name}_assemblies.tsv")
