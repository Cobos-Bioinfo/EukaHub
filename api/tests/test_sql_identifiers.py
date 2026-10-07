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
    "taxon sort": lambda: queries._taxon_keys(HOSTILE, True, queries.TaxonFilter()),
    "taxon gap sort": lambda: queries._taxon_keys(
        "gap_" + HOSTILE, True, queries.TaxonFilter()
    ),
    "taxon filter": lambda: queries._taxon_where(queries.TaxonFilter(filter_keys=[HOSTILE])),
    "report sort": lambda: next(queries.iter_report_tsv(
        None, queries.TaxonFilter(), sort=HOSTILE, descending=True, batch_rows=1,
    )),
    "records sort": lambda: queries._record_keys("assembly", HOSTILE, True),
    "records source": lambda: queries._record_keys(HOSTILE, "release_date", True),
}


@pytest.mark.parametrize("call", _CALLS.values(), ids=_CALLS.keys())
def test_hostile_identifiers_are_rejected_before_any_sql(call):
    with pytest.raises(ValueError, match="not an allowed SQL identifier"):
        call()


def test_everything_the_api_accepts_passes_the_guard():
    """The guard must never reject a value the endpoints' enums allow."""
    for sort in queries.TaxonSort:
        assert queries._taxon_keys(sort.value, True, queries.TaxonFilter())
    for key in queries.MetricFilter:
        filters = queries.TaxonFilter(filter_keys=[key.value], logic=FilterLogic.OR)
        assert queries._taxon_where(filters)
    for source, enum in (("assembly", queries.AssemblySort), ("annotation", queries.AnnotationSort)):
        for sort in enum:
            assert queries._record_keys(source, sort.value, True)
