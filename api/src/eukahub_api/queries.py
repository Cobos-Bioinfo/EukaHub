"""SQL read functions over the serving tables.

Returns core domain objects (``CladeMetadata``) rather than raw rows, so the
metric-percentage logic stays in ``eukahub_core`` and is shared with the
pipeline. The column list is built from the metric config, mirroring
Euka-Survey's ``_SQL_COLUMNS`` discipline: SELECT order == CladeMetadata
field order, guarded by a test.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import Enum

import psycopg
from eukahub_core.metrics import (
    COVERAGE_KEYS,
    METRIC_KEYS,
    METRICS,
    TOTAL_KEYS,
    CladeMetadata,
)
from psycopg_pool import ConnectionPool

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

# Search is scoped to the eukaryotic subtree (the app's domain), so non-eukaryote
# taxa never surface in the root picker even though `taxon` holds all of life.
EUKARYOTA_TAXID = 2759


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


def fetch_root(conn: psycopg.Connection, taxid: int) -> tuple[str, str, str]:
    """Return a root taxon's ``(name, rank, path)`` or raise ``TaxonNotFound``.

    Shared by the breakdown and export paths — both need the root's name (for
    the response / filename) and its ``ltree`` path (the subtree anchor)."""
    row = conn.execute(
        "SELECT name, rank, path FROM taxon WHERE taxid = %s", (taxid,)
    ).fetchone()
    if row is None:
        raise TaxonNotFound(taxid)
    return row


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


def fetch_children(
    conn: psycopg.Connection,
    *,
    taxid: int,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[tuple[int, str, str], list[tuple[str, str, CladeMetadata, bool]], int]:
    """Direct children of ``taxid`` (adjacency via ``parent_id``) — the cheap
    lookup the schema reserved for lazy-expanding the interactive tree.

    Sorted by ``sort`` (species count by default, so the biggest clades surface
    first) and paginated with ``limit``/``offset`` so a node with tens of
    thousands of children loads a screenful at a time. Returns
    ``((taxid, name, rank), [(name, rank, metadata, has_children), ...], total)``
    where ``total`` is the child count *before* limit/offset. Raises
    ``TaxonNotFound`` if ``taxid`` is absent; a present-but-childless taxon
    (e.g. a species leaf) returns an empty list, not an error.

    ``sort`` is interpolated as an identifier, so callers must pass a
    SortColumn-validated value (the endpoint does). A LEFT JOIN keeps children
    that lack a rollup row (zero-filled), and each child carries a
    ``has_children`` flag (one indexed EXISTS probe) so the UI shows an expand
    affordance without another round-trip.
    """
    parent_name, parent_rank, _path = fetch_root(conn, taxid)

    feature_cols = ", ".join(f"f.{c}" for c in _FEATURE_COLS)
    # COUNT(*) OVER () rides along for the total child count (before paging);
    # `taxid <> parent_id` drops the root's self-parent when listing its children.
    sql = (
        f"SELECT t.taxid, t.name, t.rank, {feature_cols}, "
        "EXISTS (SELECT 1 FROM taxon c WHERE c.parent_id = t.taxid) AS has_children, "
        "COUNT(*) OVER () "
        "FROM taxon t "
        "LEFT JOIN clade_features f USING (taxid) "
        "WHERE t.parent_id = %s AND t.taxid <> t.parent_id "
        f"ORDER BY COALESCE(f.{sort}, 0) DESC, t.name "
        "LIMIT %s OFFSET %s"
    )
    rows = conn.execute(sql, (taxid, limit, offset)).fetchall()

    parent_ref = (taxid, parent_name, parent_rank)
    if not rows:
        return parent_ref, [], 0
    total = rows[0][-1]
    items: list[tuple[str, str, CladeMetadata, bool]] = []
    for taxid_, name, rank, *rest in rows:
        *features, has_children, _row_total = rest
        meta = (
            CladeMetadata.zero(taxid_)  # LEFT JOIN NULLs — no clade_features row
            if features[0] is None
            else CladeMetadata(taxid_, *features)
        )
        items.append((name, rank, meta, has_children))
    return parent_ref, items, total


def _secondary_sort_key(sort_by_key: str) -> str:
    """Tiebreaker column for a primary sort column (ported verbatim from
    Euka-Survey): a ``c_*`` sort tie-breaks by its matching ``s_*``, anything
    else by ``c_ass``. Both are applied DESC, so ordering matches the old app."""
    if sort_by_key.startswith("c_"):
        return sort_by_key.replace("c_", "s_", 1)
    return "c_ass"


def _breakdown_where(
    root_path: str,
    rank: str,
    exclude_empty: bool,
    filter_keys: list[str],
    logic: FilterLogic,
) -> tuple[list[str], list]:
    """Build the shared WHERE for the breakdown/export subtree query.

    ``path <@ root_path`` = the whole subtree; the rank filter picks the level
    (both ride indexes: GiST on path, btree on rank). ``exclude_empty`` and the
    resource filters push down as ``f.<col> > 0`` predicates. ``rank`` and the
    filter columns are interpolated, so callers must pass enum-validated values.
    """
    where = ["t.path <@ %s::ltree", "t.rank = %s"]
    params: list = [root_path, rank]
    if exclude_empty:
        where.append("(" + " OR ".join(f"f.{c} > 0" for c in COVERAGE_KEYS) + ")")
    if filter_keys:
        joiner = " AND " if logic is FilterLogic.AND else " OR "
        where.append("(" + joiner.join(f"f.c_{k} > 0" for k in filter_keys) + ")")
    return where, params


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
    root_name, root_rank, root_path = fetch_root(conn, root_taxid)
    where, params = _breakdown_where(root_path, rank, exclude_empty, filter_keys, logic)

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


# Public TSV schema (ported from Euka-Survey's generate_tsv): fixed prefix, then
# every per-metric species-covered count, then every per-metric total — all in
# METRICS order, so header and row stay aligned with the SELECT below.
EXPORT_HEADER: tuple[str, ...] = (
    ("taxon_id", "name", "total_species")
    + tuple(m.tsv_count_column for m in METRICS)
    + tuple(m.tsv_total_column for m in METRICS)
)
# SELECT columns matching EXPORT_HEADER position-for-position.
_EXPORT_COLS: str = ", ".join(
    ("t.taxid", "t.name", "f.n_rows")
    + tuple(f"f.{c}" for c in COVERAGE_KEYS)
    + tuple(f"f.{c}" for c in TOTAL_KEYS)
)


def _tsv_cell(value: object) -> str:
    """Render one TSV cell; neutralize any tab/newline so rows can't break."""
    return str(value).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def iter_export_tsv(
    pool: ConnectionPool,
    *,
    root_path: str,
    rank: str,
    sort: str,
    filter_keys: list[str],
    logic: FilterLogic,
    exclude_empty: bool,
) -> Iterator[str]:
    """Stream the full breakdown at ``rank`` as TSV lines (no limit).

    The generator owns its pooled connection and a **server-side** cursor for
    the whole stream, so even a huge export (e.g. a big root at species rank,
    >1M rows) never materializes in memory. Callers validate ``rank``/``sort``/
    ``filter_keys`` via the enums; ``root_path`` comes from ``fetch_root``.
    """
    where, params = _breakdown_where(root_path, rank, exclude_empty, filter_keys, logic)
    secondary = _secondary_sort_key(sort)
    sql = (
        f"SELECT {_EXPORT_COLS} "
        "FROM taxon t "
        "JOIN clade_features f USING (taxid) "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY f.{sort} DESC, f.{secondary} DESC"
    )

    yield "\t".join(EXPORT_HEADER) + "\n"
    with pool.connection() as conn, conn.cursor(name="export") as cur:
        cur.itersize = 2000  # server-side fetch chunk
        cur.execute(sql, params)
        for row in cur:
            yield "\t".join(_tsv_cell(v) for v in row) + "\n"


def search_taxa(
    conn: psycopg.Connection, query: str, limit: int
) -> list[tuple[int, str, str]]:
    """Case-insensitive name search → ``(taxid, name, rank)`` rows.

    Substring match (``ILIKE %q%``, served by the ``pg_trgm`` GIN index on
    ``name``), ordered prefix-matches-first, then shortest, then alphabetical —
    the useful order for a root picker. Wildcards in ``query`` are escaped so
    they match literally. Results are scoped to the eukaryotic subtree.
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = conn.execute(
        "SELECT taxid, name, rank FROM taxon "
        "WHERE name ILIKE %(sub)s "
        "AND path <@ (SELECT path FROM taxon WHERE taxid = %(euk)s) "
        "ORDER BY (name ILIKE %(pre)s) DESC, length(name), name "
        "LIMIT %(lim)s",
        {"sub": f"%{escaped}%", "pre": f"{escaped}%", "lim": limit, "euk": EUKARYOTA_TAXID},
    ).fetchall()
    return rows
