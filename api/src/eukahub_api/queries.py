"""SQL read functions over the serving tables.

Returns core domain objects (``CladeMetadata``) rather than raw rows, so the
metric-percentage logic stays in ``eukahub_core`` and is shared with the
pipeline. The column list is built from the metric config, mirroring
Euka-Survey's ``_SQL_COLUMNS`` discipline: SELECT order == CladeMetadata
field order, guarded by a test.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum

import psycopg
from eukahub_core.metrics import (
    COMPOSITION_COLUMNS,
    COVERAGE_KEYS,
    METRIC_KEYS,
    METRICS,
    QUALITY_STATS,
    TOTAL_KEYS,
    CladeMetadata,
)
from eukahub_core.taxonomy import EUKARYOTA_TAXID, SPINE_TAXIDS, UNIT_RANKS
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from eukahub_api.clade_sets import SetTaxon
from eukahub_api.pagination import Key, Page, beyond, key_columns, order_by, page
from eukahub_api.pagination import decode as decode_cursor

# n_rows, then c_* (COVERAGE_KEYS), then s_* (TOTAL_KEYS), then the additive
# composition columns — the exact tail of CladeMetadata's constructor after
# taxid, so `CladeMetadata(taxid, *features)` stays positional.
_FEATURE_COLS: tuple[str, ...] = (
    ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS + COMPOSITION_COLUMNS
)

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

# Sort columns for the per-record drill-down lists (interpolated as identifiers,
# so they must be a closed, validated set — hence enums).
_ASSEMBLY_SORTS: tuple[str, ...] = ("release_date", "contig_n50", "total_sequence_length")
AssemblySort = Enum("AssemblySort", {c: c for c in _ASSEMBLY_SORTS}, type=str)
_ANNOTATION_SORTS: tuple[str, ...] = ("busco_complete", "protein_coding_count", "release_date")
AnnotationSort = Enum("AnnotationSort", {c: c for c in _ANNOTATION_SORTS}, type=str)
# Per-record tables and the columns each may be sorted by.
_RECORD_SORTS: dict[str, tuple[str, ...]] = {
    "assembly": _ASSEMBLY_SORTS,
    "annotation": _ANNOTATION_SORTS,
}


def _identifier(value: str, allowed: Collection[str]) -> str:
    """Return ``value`` if it is one of ``allowed``, else raise ``ValueError``.

    Every caller-supplied name interpolated into SQL text passes through here, so
    the queries stay safe even if an endpoint forgets its enum."""
    if value not in allowed:
        raise ValueError(f"not an allowed SQL identifier: {value!r}")
    return value


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class FilterLogic(str, Enum):
    """How multiple resource-presence filters combine (ported verbatim)."""

    AND = "AND"
    OR = "OR"

# A taxon is "infraspecific" (below species) iff a proper ancestor in its path
# is a species or an informal species: subspecies, strains, varietas, etc. Each
# is a single unit (n_rows=1), so the frontend renders it as leaf detail. One
# indexed GiST (`@>`) probe per lookup.
_UNIT_RANKS_SQL = ", ".join(f"'{r}'" for r in UNIT_RANKS)
_IS_INFRASPECIFIC = (
    "EXISTS (SELECT 1 FROM taxon a WHERE a.path @> {path} "
    f"AND a.rank IN ({_UNIT_RANKS_SQL}) AND a.taxid <> {{self}})"
)

# LEFT JOIN: a taxon may exist in `taxon` but have no rollup row (the rollup
# covers the eukaryotic subtree only). Those come back with NULL features and
# are zero-filled below.
_SUMMARY_SQL = (
    f"SELECT t.name, t.rank, {', '.join('f.' + c for c in _FEATURE_COLS)}, "
    f"{_IS_INFRASPECIFIC.format(path='t.path', self='t.taxid')} AS is_infraspecific "
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


def fetch_summary(
    conn: psycopg.Connection, taxid: int
) -> tuple[str, str, CladeMetadata, bool]:
    """Return ``(name, rank, metadata, is_infraspecific)`` for one taxon.

    Raises ``TaxonNotFound`` if the taxid is not in the taxonomy. A taxon with
    no rollup row yields a zero-filled ``CladeMetadata``. ``is_infraspecific`` is
    True for below-species taxa (subspecies/strains/...), each a single unit
    (``n_rows == 1``) whose data also counts for its species.
    """
    row = conn.execute(_SUMMARY_SQL, (taxid,)).fetchone()
    if row is None:
        raise TaxonNotFound(taxid)

    name, rank, *rest = row
    is_infraspecific: bool = rest.pop()  # trailing EXISTS column
    features = rest
    if features[0] is None:  # LEFT JOIN produced NULLs — no clade_features row
        return name, rank, CladeMetadata.zero(taxid), is_infraspecific
    return name, rank, CladeMetadata(taxid, *features), is_infraspecific


@dataclass(frozen=True, slots=True)
class TaxonRow:
    """One taxon with its lineage, rollup and quality stats (see ``fetch_taxon``)."""

    name: str
    rank: str
    lineage: list[tuple[int, str, str]]  # (taxid, name, rank), root first, the taxon last
    is_infraspecific: bool
    has_children: bool
    meta: CladeMetadata
    stats: dict[str, float | None]  # QUALITY_STATS over every record in the subtree


def fetch_taxon(conn: psycopg.Connection, taxid: int) -> TaxonRow:
    """One taxon with its lineage, rollup row (zero-filled when it has none) and
    the quality stats of the records under it. The ancestors are the labels of
    its path, so they are primary-key lookups. Raises ``TaxonNotFound``."""
    row = conn.execute(
        f"SELECT t.name, t.rank, ltree2text(t.path), "
        "EXISTS (SELECT 1 FROM taxon c WHERE c.parent_id = t.taxid AND c.taxid <> t.taxid), "
        f"{', '.join('f.' + c for c in _FEATURE_COLS)} "
        "FROM taxon t LEFT JOIN clade_features f USING (taxid) WHERE t.taxid = %s",
        (taxid,),
    ).fetchone()
    if row is None:
        raise TaxonNotFound(taxid)
    name, rank, path, has_children, *features = row
    labels = [int(label) for label in path.split(".")]
    ranks = {
        t: (n, r)
        for t, n, r in conn.execute(
            "SELECT taxid, name, rank FROM taxon WHERE taxid = ANY(%s)", (labels,)
        ).fetchall()
    }
    lineage = [(t, *ranks[t]) for t in labels if t in ranks]
    stats: dict[str, float | None] = {}
    for source in ("assembly", "annotation"):
        stats |= _fetch_quality_stats(conn, source, path)[1]
    return TaxonRow(
        name=name,
        rank=rank,
        lineage=lineage,
        is_infraspecific=any(r in UNIT_RANKS for _t, _n, r in lineage[:-1]),
        has_children=has_children,
        meta=(
            CladeMetadata.zero(taxid) if features[0] is None else CladeMetadata(taxid, *features)
        ),
        stats={q.key: stats[q.key] for q in QUALITY_STATS},
    )


def fetch_direct_totals(
    conn: psycopg.Connection, taxid: int, meta: CladeMetadata
) -> dict[str, int]:
    """Per-resource records attached to the taxon itself rather than to a finer
    taxon below it: its subtree totals minus its children's."""
    below = conn.execute(
        f"SELECT {', '.join(f'COALESCE(sum(f.{c}), 0)' for c in TOTAL_KEYS)} "
        "FROM taxon c JOIN clade_features f USING (taxid) "
        "WHERE c.parent_id = %s AND c.taxid <> c.parent_id",
        (taxid,),
    ).fetchone()
    return {
        key: getattr(meta, f"s_{key}") - int(n) for key, n in zip(METRIC_KEYS, below, strict=True)
    }


def fetch_overview(
    conn: psycopg.Connection, featured_taxids: Sequence[int]
) -> tuple[CladeMetadata, list[tuple[int, str, int, int, int, int]]]:
    """Landing-page "at a glance" data in one request.

    Returns ``(eukaryota_metadata, featured)`` where ``featured`` is one tuple
    ``(taxid, name, n_rows, s_ass, c_ass, c_ann)`` per featured group present in
    the DB, in ``featured_taxids`` order. Two small indexed lookups: Eukaryota's
    own rollup (the global totals) and the featured clades' rollups. A featured
    taxid missing from ``clade_features`` (e.g. a sliced CI DB) is dropped, never
    an error, so the section degrades gracefully."""
    _name, _rank, totals, _inf = fetch_summary(conn, EUKARYOTA_TAXID)

    rows = conn.execute(
        "SELECT t.taxid, t.name, f.n_rows, f.s_ass, f.c_ass, f.c_ann "
        "FROM taxon t JOIN clade_features f USING (taxid) "
        "WHERE t.taxid = ANY(%s)",
        (list(featured_taxids),),
    ).fetchall()
    by_id = {r[0]: r for r in rows}
    featured = [by_id[t] for t in featured_taxids if t in by_id]
    return totals, featured


def fetch_dataset_meta(
    conn: psycopg.Connection,
) -> tuple[object, int, int, int, int] | None:
    """The dataset provenance stamp: ``(built_at, taxon_count, assembly_count,
    annotation_count, clade_count)`` from the single ``dataset_meta`` row, or
    ``None`` before the first build has stamped one (a valid empty state)."""
    return conn.execute(
        "SELECT built_at, taxon_count, assembly_count, annotation_count, clade_count "
        "FROM dataset_meta LIMIT 1"
    ).fetchone()


def fetch_compare(
    conn: psycopg.Connection, taxids: list[int]
) -> list[tuple[int, str, str, CladeMetadata, dict[str, float | None]]]:
    """Per-group data for the compare view — one entry per taxid, in input order.

    Each entry is ``(taxid, name, rank, metadata, quality)`` where ``metadata`` is
    the clade's rollup (species count + per-resource coverage/total) and
    ``quality`` merges the live assembly + annotation distribution stats (median
    genome size / contig N50, best BUSCO, median genes) over the subtree — the
    same stats the drill-down endpoints expose, computed once per group. An
    unknown taxid is skipped (a stale shared link degrades gracefully rather than
    404-ing the whole comparison)."""
    groups: list[tuple[int, str, str, CladeMetadata, dict[str, float | None]]] = []
    for taxid in taxids:
        try:
            name, rank, path = fetch_root(conn, taxid)
        except TaxonNotFound:
            continue
        _n, _r, meta, _inf = fetch_summary(conn, taxid)
        _ass_total, ass_stats = _fetch_quality_stats(conn, "assembly", path)
        _ann_total, ann_stats = _fetch_quality_stats(conn, "annotation", path)
        groups.append((taxid, name, rank, meta, {**ass_stats, **ann_stats}))
    return groups


def fetch_children(
    conn: psycopg.Connection,
    *,
    taxid: int,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[tuple[int, str, str], list[tuple[str, str, CladeMetadata, bool, bool]], int]:
    """Direct children of ``taxid`` (adjacency via ``parent_id``) — the cheap
    lookup the schema reserved for lazy-expanding the interactive tree.

    Sorted by ``sort`` (species count by default, so the biggest clades surface
    first) and paginated with ``limit``/``offset`` so a node with tens of
    thousands of children loads a screenful at a time. Returns
    ``((taxid, name, rank), [(name, rank, metadata, has_children), ...], total)``
    where ``total`` is the child count *before* limit/offset. Raises
    ``TaxonNotFound`` if ``taxid`` is absent; a present-but-childless taxon
    (e.g. a species leaf) returns an empty list, not an error.

    ``sort`` is interpolated as an identifier and must be a SortColumn value.
    A LEFT JOIN keeps children that lack a rollup row (zero-filled), and each
    child carries a ``has_children`` flag (one indexed EXISTS probe) so the UI
    shows an expand affordance without another round-trip, plus an
    ``is_infraspecific`` flag: a child is below-species iff the parent already
    has a species in its path (child of a species, or of a subspecies), so one
    probe on the parent settles it for the whole page.
    """
    sort = _identifier(sort, _FEATURE_COLS)
    parent_name, parent_rank, parent_path = fetch_root(conn, taxid)
    children_infraspecific: bool = conn.execute(
        f"SELECT {_IS_INFRASPECIFIC.format(path='%s::ltree', self='0')}",
        (parent_path,),
    ).fetchone()[0]

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
    items: list[tuple[str, str, CladeMetadata, bool, bool]] = []
    for taxid_, name, rank, *rest in rows:
        *features, has_children, _row_total = rest
        meta = (
            CladeMetadata.zero(taxid_)  # LEFT JOIN NULLs — no clade_features row
            if features[0] is None
            else CladeMetadata(taxid_, *features)
        )
        items.append((name, rank, meta, has_children, children_infraspecific))
    return parent_ref, items, total


def _secondary_sort_key(sort_by_key: str) -> str:
    """Tiebreaker column for a primary sort column (ported verbatim from
    Euka-Survey): a ``c_*`` sort tie-breaks by its matching ``s_*``, anything
    else by ``c_ass``. Both are applied DESC, so ordering matches the old app."""
    if sort_by_key.startswith("c_"):
        return sort_by_key.replace("c_", "s_", 1)
    return "c_ass"


def _breakdown_order(sort: str) -> str:
    """ORDER BY for a breakdown sorted by ``sort`` (a SortColumn value). The taxid
    makes it a total order, so a LIMIT picks the same clades on every query."""
    sort = _identifier(sort, _FEATURE_COLS)
    return f"ORDER BY f.{sort} DESC, f.{_secondary_sort_key(sort)} DESC, t.taxid"


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
    resource filters push down as ``f.<col> > 0`` predicates; the filter keys
    are interpolated and must be MetricFilter values.
    """
    where = ["t.path <@ %s::ltree", "t.rank = %s"]
    params: list = [root_path, rank]
    if exclude_empty:
        where.append("(" + " OR ".join(f"f.{c} > 0" for c in COVERAGE_KEYS) + ")")
    if filter_keys:
        filter_keys = [_identifier(k, METRIC_KEYS) for k in filter_keys]
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

    ``sort``/``filter_keys`` are interpolated into SQL as identifiers and must be
    SortColumn / MetricFilter values.
    """
    order = _breakdown_order(sort)
    root_name, root_rank, root_path = fetch_root(conn, root_taxid)
    where, params = _breakdown_where(root_path, rank, exclude_empty, filter_keys, logic)

    feature_cols = ", ".join(f"f.{c}" for c in _FEATURE_COLS)
    # COUNT(*) OVER () rides along, so total-before-limit costs no extra query.
    sql = (
        f"SELECT t.taxid, t.name, t.rank, {feature_cols}, COUNT(*) OVER () "
        "FROM taxon t "
        "JOIN clade_features f USING (taxid) "
        f"WHERE {' AND '.join(where)} "
        f"{order} "
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


def fetch_gaps(
    conn: psycopg.Connection,
    *,
    root_taxid: int,
    rank: str,
    resource: str,
    limit: int,
) -> tuple[tuple[int, str, str], list[tuple[str, str, CladeMetadata]], int]:
    """The biggest under-sequenced groups: descendants of ``root_taxid`` at
    ``rank`` ranked by the "gap" = species with no ``resource`` data
    (``n_rows - c_<resource>``), largest first — the app's thesis surfaced
    directly. Big clade + little coverage rises to the top; a fully-covered
    clade (gap 0) is dropped since it isn't a gap.

    Returns ``((taxid, name, rank), [(name, rank, metadata), ...], total)`` where
    ``total`` is the count of clades with any gap (before ``limit``). One indexed
    ``ltree`` subtree query — the same machinery as ``fetch_breakdown``, only the
    ordering differs. ``resource`` is interpolated as an identifier and must be a
    MetricFilter value. Raises ``TaxonNotFound`` if the root taxid is absent.
    """
    resource = _identifier(resource, METRIC_KEYS)
    root_name, root_rank, root_path = fetch_root(conn, root_taxid)
    # gap = species in the clade lacking this resource (c_<key> <= n_rows always,
    # so it is >= 0). Ordered by the gap; species count breaks ties so among
    # equal-gap clades the larger group leads.
    gap = f"(f.n_rows - f.c_{resource})"
    feature_cols = ", ".join(f"f.{c}" for c in _FEATURE_COLS)
    sql = (
        f"SELECT t.taxid, t.name, t.rank, {feature_cols}, COUNT(*) OVER () "
        "FROM taxon t "
        "JOIN clade_features f USING (taxid) "
        "WHERE t.path <@ %s::ltree AND t.rank = %s "
        f"AND {gap} > 0 "
        f"ORDER BY {gap} DESC, f.n_rows DESC "
        "LIMIT %s"
    )
    rows = conn.execute(sql, (root_path, rank, limit)).fetchall()

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
    batch_rows: int,
) -> Iterator[str]:
    """Stream the full breakdown at ``rank`` as TSV: the header, then one chunk
    per ``batch_rows`` rows, each a single server-side FETCH (no limit).

    The generator owns its pooled connection and a **server-side** cursor for
    the whole stream, so even a huge export (e.g. a big root at species rank,
    >700k rows) never materializes in memory. ``sort``/``filter_keys`` must be
    SortColumn / MetricFilter values; ``root_path`` comes from ``fetch_root``.
    """
    order = _breakdown_order(sort)
    where, params = _breakdown_where(root_path, rank, exclude_empty, filter_keys, logic)
    sql = (
        f"SELECT {_EXPORT_COLS} "
        "FROM taxon t "
        "JOIN clade_features f USING (taxid) "
        f"WHERE {' AND '.join(where)} "
        f"{order}"
    )

    yield "\t".join(EXPORT_HEADER) + "\n"
    with pool.connection() as conn, conn.cursor(name="export") as cur:
        cur.execute(sql, params)
        # Each chunk costs a thread hop through the ASGI stack; one chunk per row
        # would take ~40x longer than the query itself on a full-species export.
        while rows := cur.fetchmany(batch_rows):
            yield "".join("\t".join(_tsv_cell(v) for v in row) + "\n" for row in rows)


# Ranks named beside a search hit so that homonyms (the insect and the fungus
# genus Drosophila) can be told apart: the nearest one above the hit.
_CONTEXT_RANKS = ("class", "phylum", "kingdom")
# Below this length a misspelling has too few trigrams to match anything useful.
_SIMILAR_MIN_LENGTH = 4


def search_taxa(conn: psycopg.Connection, query: str, limit: int) -> tuple[list[dict], bool]:
    """Case-insensitive name search for the picker → ``(hits, similar)``.

    Names starting with the query come first: an exact name, then the taxa with
    the most records, then the most species. Only those are ranked by data, since
    a short query can match tens of thousands of names mid-word. Free slots go to
    mid-word matches, shortest first. When nothing matches, close spellings are
    returned instead and ``similar`` is True. Each hit carries ``context`` (its
    nearest class, phylum or kingdom) and ``has_data``. Wildcards in ``query``
    are escaped so they match literally.
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    params = {
        "q": query,
        "pre": f"{escaped}%",
        "sub": f"%{escaped}%",
        "lim": limit,
        "spine": list(SPINE_TAXIDS),
    }
    taxids = [
        r[0]
        for r in conn.execute(
            "SELECT t.taxid FROM taxon t LEFT JOIN clade_features f USING (taxid) "
            "WHERE t.name ILIKE %(pre)s AND t.taxid <> ALL(%(spine)s) "
            "ORDER BY lower(t.name) = lower(%(q)s) DESC, "
            "COALESCE(f.s_ass, 0) + COALESCE(f.s_ann, 0) + COALESCE(f.s_rna, 0) DESC, "
            "COALESCE(f.n_rows, 0) DESC, length(t.name), t.name "
            "LIMIT %(lim)s",
            params,
        )
    ]
    if len(taxids) < limit:
        params["lim"] = limit - len(taxids)
        taxids += [
            r[0]
            for r in conn.execute(
                "SELECT taxid FROM taxon "
                "WHERE name ILIKE %(sub)s AND name NOT ILIKE %(pre)s "
                "AND taxid <> ALL(%(spine)s) "
                "ORDER BY length(name), name LIMIT %(lim)s",
                params,
            )
        ]
    similar = not taxids and len(query) >= _SIMILAR_MIN_LENGTH
    if similar:
        taxids = [
            r[0]
            for r in conn.execute(
                "SELECT taxid FROM taxon WHERE name %% %(q)s AND taxid <> ALL(%(spine)s) "
                "ORDER BY similarity(name, %(q)s) DESC, length(name), name LIMIT %(lim)s",
                params,
            )
        ]
    return _search_hits(conn, taxids), similar


def _search_hits(conn: psycopg.Connection, taxids: list[int]) -> list[dict]:
    """Search hits for ``taxids``, in that order, with their context and data flag.
    The context comes from the path labels, so it costs one primary-key lookup
    per ancestor of at most ``limit`` hits."""
    if not taxids:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT t.taxid, t.name, t.rank, "
            "COALESCE(f.s_ass, 0) + COALESCE(f.s_ann, 0) + COALESCE(f.s_rna, 0) > 0 AS has_data, "
            "(SELECT a.name FROM taxon a "
            " WHERE a.taxid = ANY(string_to_array(ltree2text(subpath(t.path, 0, -1)), '.')::int[]) "
            " AND a.rank = ANY(%(ranks)s) ORDER BY nlevel(a.path) DESC LIMIT 1) AS context "
            "FROM taxon t LEFT JOIN clade_features f USING (taxid) WHERE t.taxid = ANY(%(ids)s)",
            {"ids": taxids, "ranks": list(_CONTEXT_RANKS)},
        ).fetchall()
    by_taxid = {r["taxid"]: r for r in rows}
    return [by_taxid[t] for t in taxids]


# --- Per-record drill-down (assemblies / annotations) -----------------------
# The per-record tables are small (~68k / ~18k rows) and independently sourced,
# so "everything under clade X" is a cheap subtree join to `taxon`, and the
# distribution stats (median N50 / genome size / gene count, best BUSCO) are
# computed live per request rather than precomputed — a subtree median is not
# the sum of child medians, so it can't ride the additive rollup (data-model.md).

# SELECT lists alias every column to the response-model field name, so the
# endpoint can build the Pydantic model straight from a dict_row.
_ASSEMBLY_RECORD_SELECT = (
    "a.assembly_accession, a.taxid, t.name AS organism, a.assembly_level, "
    "a.contig_n50, a.scaffold_n50, a.total_sequence_length, a.gc_percent, "
    "a.refseq_category, a.release_date, a.submitter, a.source_database, "
    "a.bioprojects, a.download_url"
)
_ANNOTATION_RECORD_SELECT = (
    "a.annotation_id, a.assembly_accession, a.taxid, t.name AS organism, "
    "a.source_database, a.provider, a.release_date, a.gff_url, a.gene_count, "
    "a.protein_coding_count, a.busco_complete, a.busco_single_copy, "
    "a.busco_duplicated, a.busco_lineage"
)


def _quality_stats_agg(source: str) -> str:
    """Build the aggregate SELECT for a source's QUALITY_STATS (median via
    ``percentile_cont``, max via ``max``). ``column``/``key`` come from the
    trusted config, so interpolating them is safe."""
    parts = []
    for q in QUALITY_STATS:
        if q.source != source:
            continue
        if q.agg == "median":
            parts.append(
                f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {q.column}) AS {q.key}"
            )
        else:  # "max" — e.g. the clade's best BUSCO
            parts.append(f"max({q.column}) AS {q.key}")
    return ", ".join(parts)


def _fetch_quality_stats(
    conn: psycopg.Connection, source: str, root_path: str
) -> tuple[int, dict[str, float | None]]:
    """Return ``(record_count, {stat_key: value})`` for a source over the subtree
    rooted at ``root_path``. ``source`` is a per-record table name."""
    source = _identifier(source, _RECORD_SORTS)
    keys = [q.key for q in QUALITY_STATS if q.source == source]
    agg = _quality_stats_agg(source)
    row = conn.execute(
        f"SELECT count(*), {agg} FROM {source} r JOIN taxon t USING (taxid) "
        "WHERE t.path <@ %s::ltree",
        (root_path,),
    ).fetchone()
    count = row[0]
    values = {k: (float(v) if v is not None else None) for k, v in zip(keys, row[1:])}
    return count, values


# Primary key and the SQL type of each sort column, per record table.
_RECORD_KEY: dict[str, str] = {"assembly": "assembly_accession", "annotation": "annotation_id"}
_RECORD_SORT_TYPES: dict[str, str] = {
    "release_date": "date",
    "contig_n50": "bigint",
    "total_sequence_length": "bigint",
    "busco_complete": "real",
    "protein_coding_count": "integer",
}
_RECORD_SELECT: dict[str, str] = {
    "assembly": _ASSEMBLY_RECORD_SELECT,
    "annotation": _ANNOTATION_RECORD_SELECT,
}


def _record_keys(source: str, sort: str, descending: bool) -> list[Key]:
    """Records sort by ``sort`` with missing values last in either direction, then
    by primary key. ``sort`` must be one of the source's sort columns."""
    sort = _identifier(sort, _RECORD_SORTS[_identifier(source, _RECORD_SORTS)])
    return [
        Key(f"(r.{sort} IS NULL)", "boolean"),
        Key(f"r.{sort}", _RECORD_SORT_TYPES[sort], descending),
        Key(f"r.{_RECORD_KEY[source]}", "text"),
    ]


def list_records(
    conn: psycopg.Connection,
    *,
    source: str,
    within_path: str | None,
    sort: str,
    descending: bool,
    limit: int,
    cursor: str | None,
) -> tuple[int, Page[dict]]:
    """One page of a record table, optionally only the records on a taxon or below
    it, as dicts keyed by the response-model fields, with the number of matching
    records. Raises ``InvalidCursor`` for a cursor of another ordering."""
    keys = _record_keys(source, sort, descending)
    ordering = f"{source}:{sort}:{'desc' if descending else 'asc'}"
    after = decode_cursor(cursor, ordering=ordering, keys=keys) if cursor else None
    where, params = ("WHERE t.path <@ %s::ltree", [within_path]) if within_path else ("", [])
    matches = (
        f"SELECT r.{_RECORD_KEY[source]} AS id, {key_columns(keys)} "
        f"FROM {source} r JOIN taxon t USING (taxid) {where}"
    )
    beyond_sql, beyond_params = beyond(keys, after) if after else ("TRUE", [])
    backward = after is not None and after.backward
    sql = (
        f"WITH m AS MATERIALIZED ({matches}), "
        f"p AS (SELECT * FROM m WHERE {beyond_sql} "
        f"ORDER BY {order_by(keys, backward=backward)} LIMIT %s) "
        f"SELECT (SELECT count(*) FROM m) AS total, {_RECORD_SELECT[source]}, "
        f"{', '.join(f'p.k{i}' for i in range(len(keys)))} "
        f"FROM p JOIN {source} a ON a.{_RECORD_KEY[source]} = p.id "
        "JOIN taxon t ON t.taxid = a.taxid "
        f"ORDER BY {order_by(keys, backward=backward, table='p')}"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, [*params, *beyond_params, limit + 1]).fetchall()
        if rows:
            total = rows[0]["total"]
        else:
            total = cur.execute(f"SELECT count(*) AS n FROM ({matches}) m", params).fetchone()["n"]
    key_names = [f"k{i}" for i in range(len(keys))]
    keys_of = [[row.pop(k) for k in key_names] for row in rows]
    for row in rows:
        del row["total"]
    return total, page(rows, keys_of, limit=limit, cursor=after, ordering=ordering)


def _quality_by_bucket(
    conn: psycopg.Connection, bucket_filter: str, params: Sequence[object]
) -> dict[int, dict[str, float | None]]:
    """QUALITY_STATS per bucket, attributing each record to every ancestor taxon
    ``b`` that matches ``bucket_filter`` (SQL over ``b``, a trusted literal).

    Ancestors are read from the record taxon's own path labels (they are taxids),
    so buckets are found by primary key instead of an ltree containment scan over
    the whole GiST index. Returns ``{bucket_taxid: {stat_key: value|None}}`` for
    buckets that carry records.
    """
    all_keys = [q.key for q in QUALITY_STATS]
    result: dict[int, dict[str, float | None]] = {}
    for source in ("assembly", "annotation"):
        keys = [q.key for q in QUALITY_STATS if q.source == source]
        if not keys:
            continue
        sql = (
            "WITH mp AS MATERIALIZED ("
            "  SELECT rec.taxid AS rec_taxid, b.taxid AS bucket_taxid"
            f"  FROM (SELECT DISTINCT taxid FROM {source}) d"
            "  JOIN taxon rec ON rec.taxid = d.taxid"
            "  CROSS JOIN LATERAL"
            "    unnest(string_to_array(ltree2text(rec.path), '.')::int[]) AS anc(taxid)"
            "  JOIN taxon b ON b.taxid = anc.taxid"
            f"  WHERE {bucket_filter}"
            ") "
            f"SELECT mp.bucket_taxid, {_quality_stats_agg(source)} "
            f"FROM {source} r JOIN mp ON mp.rec_taxid = r.taxid "
            "GROUP BY mp.bucket_taxid"
        )
        for row in conn.execute(sql, params).fetchall():
            entry = result.setdefault(row[0], {k: None for k in all_keys})
            for k, v in zip(keys, row[1:], strict=True):
                entry[k] = float(v) if v is not None else None
    return result


def fetch_breakdown_quality(
    conn: psycopg.Connection,
    *,
    root_taxid: int,
    rank: str,
    sort: str,
    filter_keys: list[str],
    logic: FilterLogic,
    exclude_empty: bool,
    limit: int,
) -> dict[int, dict[str, float | None]]:
    """Per-bucket QUALITY_STATS for the clades ``fetch_breakdown`` returns with the
    same arguments, keyed by bucket taxid (buckets without records are absent), so
    the result never outgrows the breakdown's ``limit``. Raises ``TaxonNotFound``
    for an unknown root."""
    order = _breakdown_order(sort)
    _root_name, _root_rank, root_path = fetch_root(conn, root_taxid)
    where, params = _breakdown_where(root_path, rank, exclude_empty, filter_keys, logic)
    taxids = [
        row[0]
        for row in conn.execute(
            "SELECT t.taxid FROM taxon t JOIN clade_features f USING (taxid) "
            f"WHERE {' AND '.join(where)} {order} LIMIT %s",
            [*params, limit],
        ).fetchall()
    ]
    return _quality_by_bucket(conn, "b.taxid = ANY(%s)", (taxids,))


def fetch_quality_for_taxids(
    conn: psycopg.Connection, taxids: Sequence[int]
) -> dict[int, dict[str, float | None]]:
    """QUALITY_STATS over each given clade's subtree, keyed by taxid; every
    requested taxid is present (all-``None`` when it has no records)."""
    all_keys = [q.key for q in QUALITY_STATS]
    result: dict[int, dict[str, float | None]] = {
        int(t): {k: None for k in all_keys} for t in taxids
    }
    if taxids:
        result.update(_quality_by_bucket(conn, "b.taxid = ANY(%s)", (list(taxids),)))
    return result


# --- Sets of clades ---------------------------------------------------------------

_SET_TAXA_SQL = (
    "SELECT t.taxid, t.name, t.rank, ltree2text(t.path), "
    f"{_IS_INFRASPECIFIC.format(path='t.path', self='t.taxid')}, "
    f"{', '.join('f.' + c for c in _FEATURE_COLS)} "
    "FROM taxon t LEFT JOIN clade_features f USING (taxid) "
    "WHERE t.taxid = ANY(%s)"
)


def fetch_set_taxa(conn: psycopg.Connection, taxids: Collection[int]) -> dict[int, SetTaxon]:
    """The given taxids that are in the taxonomy, with their path and rollup row
    (zero-filled when they have none). Callers bound ``taxids``: at most 40 from
    ``/aggregate``, and what the groups file names for ``/custom-groups``."""
    taxa: dict[int, SetTaxon] = {}
    for taxid, name, rank, path, infraspecific, *features in conn.execute(
        _SET_TAXA_SQL, (list(taxids),)
    ).fetchall():
        taxa[taxid] = SetTaxon(
            taxid=taxid,
            name=name,
            rank=rank,
            path=tuple(int(label) for label in path.split(".")),
            infraspecific=infraspecific,
            features=(
                CladeMetadata.zero(taxid) if features[0] is None else CladeMetadata(taxid, *features)
            ),
        )
    return taxa


def fetch_set_quality(
    conn: psycopg.Connection, pieces: Sequence[tuple[str, Sequence[str]]]
) -> dict[str, float | None]:
    """QUALITY_STATS over the records in a set of clades, given as disjoint
    pieces ``(inside_path, [outside_paths under it])``. Each path is a literal
    parameter, so every piece is an indexed subtree filter."""
    clauses, params = [], []
    for inside, outside in pieces:
        clause = "t.path <@ %s::ltree"
        if outside:
            clause += " AND NOT (" + " OR ".join(["t.path <@ %s::ltree"] * len(outside)) + ")"
        clauses.append(f"({clause})")
        params += [inside, *outside]
    result: dict[str, float | None] = dict.fromkeys(q.key for q in QUALITY_STATS)
    if not clauses:
        return result
    for source in ("assembly", "annotation"):
        keys = [q.key for q in QUALITY_STATS if q.source == source]
        row = conn.execute(
            f"SELECT {_quality_stats_agg(source)} FROM {source} r JOIN taxon t USING (taxid) "
            f"WHERE {' OR '.join(clauses)}",
            params,
        ).fetchone()
        result |= {k: float(v) if v is not None else None for k, v in zip(keys, row, strict=True)}
    return result
