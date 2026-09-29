"""Every name interpolated into SQL text is checked against a fixed set.

The endpoints already pass enum values; these call the query functions directly
with a hostile name and no database, so the check must fire before any SQL runs.
"""

from __future__ import annotations

import pytest
from eukahub_api import queries
from eukahub_api.queries import FilterLogic

HOSTILE = "n_rows; DROP TABLE taxon --"

_CALLS = {
    "children sort": lambda: queries.fetch_children(
        None, taxid=2759, sort=HOSTILE, limit=1, offset=0
    ),
    "breakdown sort": lambda: queries.fetch_breakdown(
        None, root_taxid=2759, rank="phylum", sort=HOSTILE, filter_keys=[],
        logic=FilterLogic.AND, exclude_empty=False, limit=1,
    ),
    "breakdown filter": lambda: queries._breakdown_where(
        "2759", "phylum", False, [HOSTILE], FilterLogic.AND
    ),
    "gaps resource": lambda: queries.fetch_gaps(
        None, root_taxid=2759, rank="phylum", resource=HOSTILE, limit=1
    ),
    "export sort": lambda: next(queries.iter_export_tsv(
        None, root_path="2759", rank="phylum", sort=HOSTILE, filter_keys=[],
        logic=FilterLogic.AND, exclude_empty=False,
    )),
    "quality source": lambda: queries._fetch_quality_stats(None, HOSTILE, "2759"),
    "records sort": lambda: queries._fetch_records(
        None, source="assembly", select="*", key_col="assembly_accession",
        root_path="2759", sort=HOSTILE, limit=1, offset=0,
    ),
    "records source": lambda: queries._fetch_records(
        None, source=HOSTILE, select="*", key_col="assembly_accession",
        root_path="2759", sort="release_date", limit=1, offset=0,
    ),
}


@pytest.mark.parametrize("call", _CALLS.values(), ids=_CALLS.keys())
def test_hostile_identifiers_are_rejected_before_any_sql(call):
    with pytest.raises(ValueError, match="not an allowed SQL identifier"):
        call()


def test_everything_the_api_accepts_passes_the_guard():
    """The guard must never reject a value the endpoints' enums allow."""
    for sort in queries.SortColumn:
        assert queries._identifier(sort.value, queries._FEATURE_COLS)
        assert queries._secondary_sort_key(sort.value) in queries._FEATURE_COLS
    for key in queries.MetricFilter:
        assert queries._breakdown_where("2759", "phylum", False, [key.value], FilterLogic.OR)
    for source, enum in (("assembly", queries.AssemblySort), ("annotation", queries.AnnotationSort)):
        for sort in enum:
            assert queries._identifier(sort.value, queries._RECORD_SORTS[source])
