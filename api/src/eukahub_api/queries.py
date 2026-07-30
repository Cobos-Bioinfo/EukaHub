"""SQL read functions over the serving tables.

Returns core domain objects (``CladeMetadata``) rather than raw rows, so the
metric-percentage logic stays in ``eukahub_core`` and is shared with the
pipeline. The column list is built from the metric config, mirroring
Euka-Survey's ``_SQL_COLUMNS`` discipline: SELECT order == CladeMetadata
field order, guarded by a test.
"""

from __future__ import annotations

from enum import Enum

import psycopg
from eukahub_core.metrics import COVERAGE_KEYS, METRIC_KEYS, TOTAL_KEYS, CladeMetadata

# n_rows, then c_* (COVERAGE_KEYS), then s_* (TOTAL_KEYS) — the exact tail of
# CladeMetadata's constructor after taxid.
_FEATURE_COLS: tuple[str, ...] = ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS

# --- Breakdown query-param enums --------------------------------------------
# Derived from the metric config, so the API contract (and the OpenAPI/TS
# types generated from it) can't drift from the tracked resources. They also
# make the identifiers interpolated into SQL below a closed, safe set.

# Valid sort columns: species count + every c_*/s_* feature column.
SortColumn = Enum("SortColumn", {c: c for c in _FEATURE_COLS}, type=str)
# Resource-presence filter keys ("ass", "ann", "rna", "lng").
MetricFilter = Enum("MetricFilter", {k: k for k in METRIC_KEYS}, type=str)

# Ranks the breakdown can target (ported from Euka-Survey's ALLOWED_RANKS).
ALLOWED_RANKS: tuple[str, ...] = ("phylum", "class", "order", "family", "genus", "species")
TargetRank = Enum("TargetRank", {r: r for r in ALLOWED_RANKS}, type=str)


class FilterLogic(str, Enum):
    """How multiple resource-presence filters combine (ported verbatim)."""

    AND = "AND"
    OR = "OR"

# LEFT JOIN: a taxon may exist in `taxon` but have no rollup row (the rollup
# covers the eukaryotic subtree only). Those come back with NULL features and
# are zero-filled below.
_SUMMARY_SQL = (
    f"SELECT t.name, t.rank, {', '.join('f.' + c for c in _FEATURE_COLS)} "
    "FROM taxon t "
    "LEFT JOIN clade_features f USING (taxid) "
    "WHERE t.taxid = %s"
)


class TaxonNotFound(Exception):
    """Raised when a taxid is absent from the `taxon` table."""

    def __init__(self, taxid: int) -> None:
        super().__init__(f"taxon {taxid} not found")
        self.taxid = taxid


def fetch_summary(conn: psycopg.Connection, taxid: int) -> tuple[str, str, CladeMetadata]:
    """Return ``(name, rank, metadata)`` for one taxon.

    Raises ``TaxonNotFound`` if the taxid is not in the taxonomy. A taxon with
    no rollup row yields a zero-filled ``CladeMetadata``.
    """
    row = conn.execute(_SUMMARY_SQL, (taxid,)).fetchone()
    if row is None:
        raise TaxonNotFound(taxid)

    name, rank, *features = row
    if features[0] is None:  # LEFT JOIN produced NULLs — no clade_features row
        return name, rank, CladeMetadata.zero(taxid)
    return name, rank, CladeMetadata(taxid, *features)


def fetch_lineage(conn: psycopg.Connection, taxid: int) -> list[tuple[int, str, str]]:
    """Return the root→taxon lineage as ``(taxid, name, rank)`` rows, inclusive
    of the taxon itself, ordered root-first.

    One indexed query: ``path @>`` selects the ancestors-or-self via the GiST
    index, ``nlevel(path)`` orders them by depth. No recursion, no ETE3. Raises
    ``TaxonNotFound`` if the taxid is absent (a present taxon always yields at
    least its own row)."""
    rows = conn.execute(
        "SELECT t.taxid, t.name, t.rank FROM taxon t "
        "WHERE t.path @> (SELECT path FROM taxon WHERE taxid = %s) "
        "ORDER BY nlevel(t.path)",
        (taxid,),
    ).fetchall()
    if not rows:
        raise TaxonNotFound(taxid)
    return rows


def _secondary_sort_key(sort_by_key: str) -> str:
    """Tiebreaker column for a primary sort column (ported verbatim from
    Euka-Survey): a ``c_*`` sort tie-breaks by its matching ``s_*``, anything
    else by ``c_ass``. Both are applied DESC, so ordering matches the old app."""
    if sort_by_key.startswith("c_"):
        return sort_by_key.replace("c_", "s_", 1)
    return "c_ass"


def fetch_breakdown(
    conn: psycopg.Connection,
    *,
    root_taxid: int,
    rank: str,
    sort: str,
    filter_keys: list[str],
    logic: FilterLogic,
    exclude_empty: bool,
    limit: int,
) -> tuple[tuple[int, str, str], list[tuple[str, str, CladeMetadata]], int]:
    """Descendants of ``root_taxid`` at ``rank``, with filter/sort/limit pushed
    into one indexed ``ltree`` query — the replacement for the deleted
    ``precomputed_taxa`` cache, correct for any root.

    Returns ``((taxid, name, rank), [(name, rank, metadata), ...], total)``
    where ``total`` is the match count *before* ``limit``. Raises
    ``TaxonNotFound`` if the root taxid is absent.

    ``rank``/``sort``/``filter_keys`` are interpolated into SQL as identifiers,
    so callers must pass values validated by the TargetRank / SortColumn /
    MetricFilter enums (the endpoint does).
    """
    root = conn.execute(
        "SELECT name, rank, path FROM taxon WHERE taxid = %s", (root_taxid,)
    ).fetchone()
    if root is None:
        raise TaxonNotFound(root_taxid)
    root_name, root_rank, root_path = root

    # `path <@ root_path` = the whole subtree; the rank filter picks the level.
    # Both ride indexes (GiST on path, btree on rank).
    where = ["t.path <@ %s::ltree", "t.rank = %s"]
    params: list = [root_path, rank]
    if exclude_empty:
        where.append("(" + " OR ".join(f"f.{c} > 0" for c in COVERAGE_KEYS) + ")")
    if filter_keys:
        joiner = " AND " if logic is FilterLogic.AND else " OR "
        where.append("(" + joiner.join(f"f.c_{k} > 0" for k in filter_keys) + ")")

    secondary = _secondary_sort_key(sort)
    feature_cols = ", ".join(f"f.{c}" for c in _FEATURE_COLS)
    # COUNT(*) OVER () rides along, so total-before-limit costs no extra query.
    sql = (
        f"SELECT t.taxid, t.name, t.rank, {feature_cols}, COUNT(*) OVER () "
        "FROM taxon t "
        "JOIN clade_features f USING (taxid) "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY f.{sort} DESC, f.{secondary} DESC "
        "LIMIT %s"
    )
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    root_ref = (root_taxid, root_name, root_rank)
    if not rows:
        return root_ref, [], 0
    total = rows[0][-1]
    items = [
        (name, item_rank, CladeMetadata(taxid, *features))
        for taxid, name, item_rank, *features in (row[:-1] for row in rows)
    ]
    return root_ref, items, total
