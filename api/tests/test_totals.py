"""The cached list totals and the cap on per-taxon stats. No database needed."""

from __future__ import annotations

import pytest
from eukahub_api import queries
from eukahub_api.totals import CountCache


class _Rows:
    def __init__(self, row: tuple) -> None:
        self._row = row

    def fetchone(self) -> tuple:
        return self._row


class _Connection:
    """Answers the build-stamp query and counts every count(*) it is asked for."""

    def __init__(self) -> None:
        self.built_at = "2026-10-01"
        self.counted: list[tuple[str, list]] = []

    def execute(self, sql: str, params=()) -> _Rows:
        if "dataset_meta" in sql:
            return _Rows((self.built_at,))
        self.counted.append((sql, list(params)))
        return _Rows((len(self.counted),))


def test_a_query_is_counted_once_per_build():
    conn, cache = _Connection(), CountCache()
    assert cache.count(conn, "SELECT 1", [7]) == 1
    assert cache.count(conn, "SELECT 1", [7]) == 1
    assert cache.count(conn, "SELECT 1", [8]) == 2  # other parameters, other count
    conn.built_at = "2026-11-01"  # a new dataset was installed
    assert cache.count(conn, "SELECT 1", [7]) == 3
    assert len(conn.counted) == 3


def test_a_sum_is_cached_apart_from_the_count():
    conn, cache = _Connection(), CountCache()
    assert cache.count(conn, "SELECT 1 AS n", []) == 1
    assert cache.sum(conn, "n", "SELECT 1 AS n", []) == 2
    assert cache.sum(conn, "n", "SELECT 1 AS n", []) == 2
    assert [sql.split(" FROM")[0] for sql, _ in conn.counted] == [
        "SELECT count(*)",
        "SELECT coalesce(sum(n), 0)",
    ]


def test_the_oldest_counts_are_dropped_past_the_limit():
    conn, cache = _Connection(), CountCache(max_entries=2)
    for p in (1, 2, 3):
        cache.count(conn, "SELECT 1", [p])
    cache.count(conn, "SELECT 1", [3])  # still kept
    cache.count(conn, "SELECT 1", [1])  # dropped, so counted again
    assert [params for _sql, params in conn.counted] == [[1], [2], [3], [1]]


def test_stats_for_more_taxa_than_a_page_are_refused_before_any_sql():
    with pytest.raises(ValueError, match="at most 1000"):
        queries.fetch_quality_for_taxids(None, range(queries.MAX_PAGE + 1))
