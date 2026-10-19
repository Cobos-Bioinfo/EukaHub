"""SQL read functions over the serving tables.

Returns core domain objects (``CladeMetadata``) rather than raw rows, so the
metric-percentage logic stays in ``eukahub_core`` and is shared with the
pipeline. The column list is built from the metric config, mirroring
Euka-Survey's ``_SQL_COLUMNS`` discipline: SELECT order == CladeMetadata
field order, guarded by a test.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

import psycopg
from eukahub_core.metrics import (
    ASSEMBLY_LEVELS,
    COMPOSITION_COLUMNS,
    COVERAGE_KEYS,
    EBP_MIN_CONTIG_N50,
    EBP_MIN_SCAFFOLD_N50,
    METRIC_KEYS,
    METRIC_NAMES,
    METRICS,
    QUALITY_KEYS,
    QUALITY_STATS,
    TOTAL_KEYS,
    CladeMetadata,
)
from eukahub_core.taxonomy import INFORMAL_SPECIES_RANK, SPINE_TAXIDS, UNIT_RANKS
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from eukahub_api.clade_sets import SetTaxon
from eukahub_api.pagination import Cursor, Key, Page, beyond, key_columns, order_by, page
from eukahub_api.pagination import decode as decode_cursor
from eukahub_api.schemas import COMPOSITION_FIELDS
from eukahub_api.totals import counts

# n_rows, then c_* (COVERAGE_KEYS), then s_* (TOTAL_KEYS), then the additive
# composition columns — the exact tail of CladeMetadata's constructor after
# taxid, so `CladeMetadata(taxid, *features)` stays positional.
_FEATURE_COLS: tuple[str, ...] = (
    ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS + COMPOSITION_COLUMNS
)

# --- /taxons query-parameter enums ------------------------------------------
# Derived from the metric config, so the API contract (and the OpenAPI/TS
# types generated from it) can't drift from the tracked resources. They also
# make the identifiers interpolated into SQL below a closed, safe set.

# Resource-presence filters, by resource name ("assemblies", ...).
MetricFilter = Enum("MetricFilter", {n: n for n in METRIC_NAMES}, type=str)
METRIC_KEY_OF: dict[str, str] = {m.name: m.key for m in METRICS}


def _count(column: str) -> str:
    return f"COALESCE(f.{column}, 0)"


# /taxons sorts, each named after its number in a taxon object
# (`resources.assemblies.covered` is `assemblies_covered`, `composition.chromosome` is
# `chromosome`), with the SQL it orders by and the SQL that breaks its ties.
_COUNT_SORTS: dict[str, tuple[str, str]] = {
    "species": (_count("n_rows"), _count("c_ass")),
    **{
        f"{m.name}_{field}": sql
        for m in METRICS
        for field, sql in (
            ("covered", (_count(m.coverage_key), _count(m.total_key))),
            ("missing", (f"{_count('n_rows')} - {_count(m.coverage_key)}", _count("n_rows"))),
            ("total", (_count(m.total_key), _count("c_ass"))),
        )
    },
    **{
        field: (_count(column), _count("c_ass"))
        for field, column in COMPOSITION_FIELDS.items()
    },
}
TaxonSort = Enum("TaxonSort", {s: s for s in (*_COUNT_SORTS, "name")}, type=str)

# Most rows one page of a list may hold.
MAX_PAGE = 1000

# Ranks `rank` takes: the major ranks, as on Annotrieve's taxonomy page.
ALLOWED_RANKS: tuple[str, ...] = (
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
)
TargetRank = Enum("TargetRank", {r: r for r in ALLOWED_RANKS}, type=str)

# A tree of major ranks shows these, informal species standing in for species.
_MAJOR_RANKS_SQL = ", ".join(f"'{r}'" for r in (*ALLOWED_RANKS, INFORMAL_SPECIES_RANK))
# A taxon's nearest descendants of a major rank: its children, and the children of
# any of other ranks in turn, down to a major rank. Each step is a parent_id lookup.
_NEAREST_MAJOR_SQL = (
    "WITH RECURSIVE walk AS ("
    " SELECT c.taxid, c.rank FROM taxon c WHERE c.parent_id = %s AND c.taxid <> c.parent_id"
    " UNION ALL"
    " SELECT c.taxid, c.rank FROM walk w"
    " JOIN taxon c ON c.parent_id = w.taxid AND c.taxid <> c.parent_id"
    f" WHERE w.rank NOT IN ({_MAJOR_RANKS_SQL})"
    f") SELECT taxid FROM walk WHERE rank IN ({_MAJOR_RANKS_SQL})"
)

# Sort columns for the per-record drill-down lists (interpolated as identifiers,
# so they must be a closed, validated set — hence enums).
_ASSEMBLY_SORTS: tuple[str, ...] = (
    "release_date", "contig_n50", "scaffold_n50", "total_sequence_length",
)
AssemblySort = Enum(
    "AssemblySort", {c: c for c in ("recommended", *_ASSEMBLY_SORTS)}, type=str
)
AssemblyLevel = Enum("AssemblyLevel", {k: k for k in ASSEMBLY_LEVELS}, type=str)
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
    """How multiple resource-presence filters combine."""

    AND = "and"
    OR = "or"

# A taxon is "infraspecific" (below species) iff a proper ancestor in its path
# is a species or an informal species: subspecies, strains, varietas, etc. Each
# is a single unit (n_rows=1), so the frontend renders it as leaf detail. One
# indexed GiST (`@>`) probe per lookup.
_UNIT_RANKS_SQL = ", ".join(f"'{r}'" for r in UNIT_RANKS)
_IS_INFRASPECIFIC = (
    "EXISTS (SELECT 1 FROM taxon a WHERE a.path @> {path} "
    f"AND a.rank IN ({_UNIT_RANKS_SQL}) AND a.taxid <> {{self}})"
)

class TaxonNotFound(Exception):
    """Raised when a taxid is absent from the `taxon` table."""

    def __init__(self, taxid: int) -> None:
        super().__init__(f"taxon {taxid} not found")
        self.taxid = taxid


class Root(NamedTuple):
    """A taxon a request names, by the taxid it now has."""

    taxid: int
    name: str
    rank: str
    path: str


# A taxon by its taxid or, when NCBI has merged that taxid into another, by the
# other: the second branch only runs when the first finds nothing.
_ROOT_SQL = (
    "SELECT taxid, name, rank, path FROM taxon WHERE taxid = %s "
    "UNION ALL "
    "SELECT t.taxid, t.name, t.rank, t.path FROM taxon_merged m "
    "JOIN taxon t ON t.taxid = m.merged_into WHERE m.taxid = %s "
    "LIMIT 1"
)


def fetch_root(conn: psycopg.Connection, taxid: int) -> Root:
    """The taxon ``taxid`` names, or the one it was merged into; raises
    ``TaxonNotFound`` when there is neither. Used wherever a request names a taxon:
    its name (for the response or filename) and its ``ltree`` path (the subtree
    anchor)."""
    row = conn.execute(_ROOT_SQL, (taxid, taxid)).fetchone()
    if row is None:
        raise TaxonNotFound(taxid)
    return Root(*row)


def _direct_totals(
    conn: psycopg.Connection, units: Mapping[int, CladeMetadata]
) -> dict[int, dict[str, int]]:
    """Per-resource records attached to each of these taxa itself rather than to a
    finer taxon below it: its totals minus its children's."""
    if not units:
        return {}
    below = {
        parent: sums
        for parent, *sums in conn.execute(
            f"SELECT c.parent_id, {', '.join(f'sum(f.{c})' for c in TOTAL_KEYS)} "
            "FROM taxon c JOIN clade_features f USING (taxid) "
            "WHERE c.parent_id = ANY(%s) AND c.taxid <> c.parent_id GROUP BY c.parent_id",
            (list(units),),
        ).fetchall()
    }
    return {
        taxid: {
            m.name: getattr(meta, m.total_key) - int(n)
            for m, n in zip(METRICS, below.get(taxid, [0] * len(TOTAL_KEYS)), strict=True)
        }
        for taxid, meta in units.items()
    }


def _list_one(conn: psycopg.Connection, taxid: int) -> list[TaxonListRow]:
    _total, result = list_taxa(
        conn, TaxonFilter(taxids=[taxid]), sort=None, descending=True, limit=1, cursor=None
    )
    return result.rows


def fetch_taxon(conn: psycopg.Connection, taxid: int) -> TaxonListRow:
    """One taxon, built exactly as ``list_taxa`` builds a list item: for a merged
    taxid, the taxon it was merged into. Raises ``TaxonNotFound``."""
    return (_list_one(conn, taxid) or _list_one(conn, fetch_root(conn, taxid).taxid))[0]


def fetch_ancestors(conn: psycopg.Connection, taxid: int) -> list[TaxonListRow]:
    """The root, every taxon down to ``taxid``, and the taxon itself, in that order:
    the labels of its path. Raises ``TaxonNotFound``."""
    labels = [int(label) for label in fetch_root(conn, taxid).path.split(".")]
    _total, result = list_taxa(
        conn, TaxonFilter(taxids=labels), sort=None, descending=True, limit=len(labels), cursor=None
    )
    depth = {t: i for i, t in enumerate(labels)}
    return sorted(result.rows, key=lambda r: depth[r.meta.taxid])


def fetch_taxon_stats(
    conn: psycopg.Connection, taxid: int
) -> tuple[Root, dict[str, float | None]]:
    """The taxon (as ``fetch_root`` finds it) and its QUALITY_STATS over the records
    on or below it, computed at build time. Raises ``TaxonNotFound``."""
    root = fetch_root(conn, taxid)
    return root, _clade_stats(conn, [root.taxid]).get(root.taxid, dict.fromkeys(QUALITY_KEYS))


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


@dataclass(frozen=True, slots=True)
class TaxonFilter:
    """Which taxa ``/taxons`` lists; every field set narrows the list further."""

    q: str | None = None  # name or common name contains it (with ``fuzzy``: spelled like it)
    fuzzy: bool = False
    parent: int | None = None  # direct children of this taxon
    major_ranks: bool = False  # with parent: its nearest descendants of a major rank
    within: int | None = None  # this taxon and everything below it
    within_path: str | None = None  # the path of ``within``
    rank: str | None = None
    taxids: Sequence[int] = ()
    filter_keys: Sequence[str] = ()  # metric keys: has data for these resources
    logic: FilterLogic = FilterLogic.AND
    exclude_empty: bool = False  # has data for any resource


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _taxon_where(f: TaxonFilter) -> tuple[list[str], list[object]]:
    where: list[str] = []
    params: list[object] = []
    if f.q is not None:
        if f.fuzzy:
            where.append("(t.name %% %s OR t.common_name %% %s)")
            params += [f.q] * 2
        else:
            where.append("(t.name ILIKE %s OR t.common_name ILIKE %s)")
            params += [f"%{_escape_like(f.q)}%"] * 2
        # The root and "cellular organisms" are never what a name search is after.
        where.append("t.taxid <> ALL(%s)")
        params.append(list(SPINE_TAXIDS))
    if f.parent is not None and f.major_ranks:
        where.append(f"t.taxid IN ({_NEAREST_MAJOR_SQL})")
        params.append(f.parent)
    elif f.parent is not None:
        where.append("t.parent_id = %s AND t.taxid <> t.parent_id")
        params.append(f.parent)
    if f.within_path is not None:
        where.append("t.path <@ %s::ltree")
        params.append(f.within_path)
    if f.rank is not None:
        where.append("t.rank = %s")
        params.append(f.rank)
    if f.taxids:
        where.append("t.taxid = ANY(%s)")
        params.append(list(f.taxids))
    if f.exclude_empty:
        where.append("(" + " OR ".join(f"f.{c} > 0" for c in COVERAGE_KEYS) + ")")
    if f.filter_keys:
        keys = [_identifier(k, METRIC_KEYS) for k in f.filter_keys]
        joiner = " AND " if f.logic is FilterLogic.AND else " OR "
        where.append("(" + joiner.join(f"f.c_{k} > 0" for k in keys) + ")")
    return where, params


_NAME_KEYS = [Key("t.name", "text"), Key("t.taxid", "integer")]


def _taxon_keys(
    sort: str | None, descending: bool, f: TaxonFilter
) -> tuple[str, list[Key], list[object]]:
    """``(ordering name, keys, parameters of the keys' SQL)`` for a /taxons sort.
    Without ``sort``, a name search is ordered by relevance (or by similarity when
    fuzzy) and anything else by species count."""
    if sort is None and f.q is not None and f.fuzzy:
        return (
            f"similar:{f.q}",
            [
                Key("greatest(similarity(t.name, %s), similarity(t.common_name, %s))", "real", True),
                Key("length(t.name)", "integer"),
                *_NAME_KEYS,
            ],
            [f.q] * 2,
        )
    if sort is None and f.q is not None:
        # An exact name first; then names starting with the query, those with the
        # most records and species first; then the rest, shortest first. Only the
        # prefix matches are ranked by data, read only for them. A common name counts
        # as a name.
        exact = "(lower(t.name) = lower(%s) OR COALESCE(lower(t.common_name) = lower(%s), false))"
        prefix = "(t.name ILIKE %s OR COALESCE(t.common_name ILIKE %s, false))"
        data = "(SELECT g.{} FROM clade_features g WHERE g.taxid = t.taxid)"
        records = data.format(" + g.".join(TOTAL_KEYS))
        species = data.format("n_rows")
        return (
            f"relevance:{f.q}",
            [
                Key(exact, "boolean", True),
                Key(prefix, "boolean", True),
                Key(f"CASE WHEN {prefix} THEN COALESCE({records}, 0) ELSE 0 END", "integer", True),
                Key(f"CASE WHEN {prefix} THEN COALESCE({species}, 0) ELSE 0 END", "integer", True),
                Key("length(t.name)", "integer"),
                *_NAME_KEYS,
            ],
            [f.q, f.q, *[f"{_escape_like(f.q)}%"] * 6],
        )
    sort = _identifier(sort or "species", [t.value for t in TaxonSort])
    order = "desc" if descending else "asc"
    if sort == "name":
        return f"name:{order}", [Key("t.name", "text", descending), Key("t.taxid", "integer")], []
    primary, secondary = _COUNT_SORTS[sort]
    return (
        f"{sort}:{order}",
        [Key(primary, "integer", descending), Key(secondary, "integer", descending), *_NAME_KEYS],
        [],
    )


# Ranks named beside a taxon so that homonyms (the insect and the fungus genus
# Drosophila) can be told apart: the nearest one above it.
_CONTEXT_RANKS = ("class", "phylum", "kingdom")
_CONTEXT_RANKS_SQL = ", ".join(f"'{r}'" for r in _CONTEXT_RANKS)

_HAS_CHILDREN_SQL = (
    "EXISTS (SELECT 1 FROM taxon c WHERE c.parent_id = t.taxid AND c.taxid <> t.taxid)"
)
_HAS_MAJOR_CHILDREN_SQL = (
    "EXISTS (SELECT 1 FROM taxon c WHERE c.path <@ t.path AND c.taxid <> t.taxid "
    f"AND c.rank IN ({_MAJOR_RANKS_SQL}))"
)


def _taxon_item_sql(major_ranks: bool) -> str:
    """Per listed taxon: its rollup, whether it has children (with ``major_ranks``,
    any descendant of a major rank), and from its ancestors (the labels of its
    path, so primary-key lookups) whether it sits below a species and its nearest
    class, phylum or kingdom."""
    has_children = _HAS_MAJOR_CHILDREN_SQL if major_ranks else _HAS_CHILDREN_SQL
    return (
        f"t.taxid, t.name, t.common_name, t.rank, {', '.join('f.' + c for c in _FEATURE_COLS)}, "
        f"{has_children} AS has_children, "
        "COALESCE(anc.infraspecific, false) AS is_infraspecific, anc.context "
        "FROM p JOIN taxon t ON t.taxid = p.id LEFT JOIN clade_features f ON f.taxid = t.taxid "
        "LEFT JOIN LATERAL ("
        f"  SELECT bool_or(a.rank IN ({_UNIT_RANKS_SQL})) AS infraspecific,"
        "   (array_agg(a.name ORDER BY nlevel(a.path) DESC)"
        f"    FILTER (WHERE a.rank IN ({_CONTEXT_RANKS_SQL})))[1] AS context"
        "   FROM taxon a"
        "   WHERE a.taxid = ANY(string_to_array(ltree2text(subpath(t.path, 0, -1)), '.')::int[])"
        ") anc ON true"
    )


@dataclass(frozen=True, slots=True)
class TaxonListRow:
    meta: CladeMetadata
    name: str
    common_name: str | None
    rank: str
    context: str | None
    is_infraspecific: bool
    has_children: bool
    direct: dict[str, int] | None  # species and finer taxa only


def list_taxa(
    conn: psycopg.Connection,
    f: TaxonFilter,
    *,
    sort: str | None,
    descending: bool,
    limit: int,
    cursor: str | None,
) -> tuple[int, Page[TaxonListRow]]:
    """One page of the taxa matching ``f``, with the number of matches. ``sort`` is
    a TaxonSort value or None for the default order. Raises ``InvalidCursor`` for a
    cursor of another ordering."""
    ordering, keys, key_params = _taxon_keys(sort, descending, f)
    after = decode_cursor(cursor, ordering=ordering, keys=keys) if cursor else None
    where, where_params = _taxon_where(f)
    filters_need_features = f.exclude_empty or bool(f.filter_keys)
    needs_features = filters_need_features or any("f." in k.sql for k in keys)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = counts.count(
        conn,
        "SELECT t.taxid FROM taxon t "
        f"{'LEFT JOIN clade_features f USING (taxid) ' if filters_need_features else ''}{where_sql}",
        where_params,
    )
    matches = (
        f"SELECT t.taxid AS id, {key_columns(keys)} FROM taxon t "
        f"{'LEFT JOIN clade_features f USING (taxid) ' if needs_features else ''}{where_sql}"
    )
    beyond_sql, beyond_params = beyond(keys, after) if after else ("TRUE", [])
    backward = after is not None and after.backward
    # The page is the top `limit + 1` rows of a sort, so the database keeps only
    # that many in memory; the details are read for those rows alone.
    sql = (
        f"WITH p AS (SELECT * FROM ({matches}) m WHERE {beyond_sql} "
        f"ORDER BY {order_by(keys, backward=backward)} LIMIT %s) "
        f"SELECT {', '.join(f'p.k{i}' for i in range(len(keys)))}, "
        f"{_taxon_item_sql(f.major_ranks)} "
        f"ORDER BY {order_by(keys, backward=backward, table='p')}"
    )
    rows = conn.execute(sql, [*key_params, *where_params, *beyond_params, limit + 1]).fetchall()
    n_keys = len(keys)
    keys_of = [list(row[:n_keys]) for row in rows]
    parsed = []
    for row in rows:
        taxid, name, common_name, rank, *rest = row[n_keys:]
        *features, has_children, is_infraspecific, context = rest
        meta = (
            CladeMetadata.zero(taxid) if features[0] is None else CladeMetadata(taxid, *features)
        )
        parsed.append((meta, name, common_name, rank, context, is_infraspecific, has_children))
    direct = _direct_totals(
        conn, {p[0].taxid: p[0] for p in parsed if p[5] or p[3] in UNIT_RANKS}
    )
    items = [TaxonListRow(*p, direct=direct.get(p[0].taxid)) for p in parsed]
    return total, page(items, keys_of, limit=limit, cursor=after, ordering=ordering)


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
    ("t.taxid", "t.name")
    + tuple(f"COALESCE(f.{c}, 0)" for c in ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS)
)


def _tsv_cell(value: object) -> str:
    """Render one TSV cell; neutralize any tab/newline so rows can't break."""
    return str(value).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def iter_report_tsv(
    pool: ConnectionPool,
    f: TaxonFilter,
    *,
    sort: str | None,
    descending: bool,
    batch_rows: int,
) -> Iterator[str]:
    """Stream every taxon matching ``f`` as TSV, in the order ``/taxons`` lists
    them: the header, then one chunk per ``batch_rows`` rows, each a single
    server-side FETCH.

    The generator owns its pooled connection and a **server-side** cursor for
    the whole stream, so even a huge report (every eukaryote species, >700k rows)
    never materializes in memory.
    """
    _ordering, keys, key_params = _taxon_keys(sort, descending, f)
    where, where_params = _taxon_where(f)
    order = ", ".join(f"{k.sql} {'DESC' if k.descending else 'ASC'}" for k in keys)
    sql = (
        f"SELECT {_EXPORT_COLS} FROM taxon t LEFT JOIN clade_features f USING (taxid) "
        f"{'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY {order}"
    )

    yield "\t".join(EXPORT_HEADER) + "\n"
    with pool.connection() as conn, conn.cursor(name="report") as cur:
        cur.execute(sql, [*where_params, *key_params])
        # Each chunk costs a thread hop through the ASGI stack; one chunk per row
        # would take ~40x longer than the query itself on a full-species report.
        while rows := cur.fetchmany(batch_rows):
            yield "".join("\t".join(_tsv_cell(v) for v in row) + "\n" for row in rows)


# --- Per-record drill-down (assemblies / annotations) -----------------------
# "Everything under clade X" is a subtree join to `taxon`. A clade's distribution
# stats (median N50 / genome size / gene count, best BUSCO) are computed at build
# time from its records (`clade_stats`); only a set of clades needs its records here.

# SELECT lists alias every column to the response-model field name, so the
# endpoint can build the Pydantic model straight from a dict_row.
_ASSEMBLY_RECORD_SELECT = (
    "a.assembly_accession, a.taxid, t.name AS organism_name, a.assembly_level, "
    "a.contig_n50, a.scaffold_n50, a.total_sequence_length, a.gc_percent, "
    "a.refseq_category, a.release_date, a.submitter, a.source_database, "
    "a.bioprojects, a.download_url, a.species_taxid"
)
_ANNOTATION_RECORD_SELECT = (
    "a.annotation_id, a.assembly_accession, a.taxid, t.name AS organism_name, "
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


# Primary key and the SQL type of each sort column, per record table.
_RECORD_KEY: dict[str, str] = {"assembly": "assembly_accession", "annotation": "annotation_id"}
_RECORD_SORT_TYPES: dict[str, str] = {
    "release_date": "date",
    "contig_n50": "bigint",
    "scaffold_n50": "bigint",
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


def _records_sql(
    source: str, within_path: str | None, keys: Sequence[Key], after: Cursor | None,
    limit: int | None,
) -> tuple[str, list[object]]:
    """The records of ``source`` on or below ``within_path`` in the order of ``keys``,
    as response rows followed by their key values k0, k1, ...: the page after (or
    before) ``after`` when ``limit`` is set, else every one."""
    where, params = ("WHERE t.path <@ %s::ltree", [within_path]) if within_path else ("", [])
    beyond_sql, beyond_params = beyond(keys, after) if after else ("TRUE", [])
    backward = after is not None and after.backward
    sql = (
        f"WITH p AS (SELECT * FROM (SELECT r.{_RECORD_KEY[source]} AS id, "
        f"{key_columns(keys)} FROM {source} r JOIN taxon t USING (taxid) {where}) m "
        f"WHERE {beyond_sql} ORDER BY {order_by(keys, backward=backward)} "
        f"{'LIMIT %s' if limit is not None else ''}) "
        f"SELECT {_RECORD_SELECT[source]}, {', '.join(f'p.k{i}' for i in range(len(keys)))} "
        f"FROM p JOIN {source} a ON a.{_RECORD_KEY[source]} = p.id "
        "JOIN taxon t ON t.taxid = a.taxid "
        f"ORDER BY {order_by(keys, backward=backward, table='p')}"
    )
    return sql, [*params, *beyond_params, *([limit] if limit is not None else [])]


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
    total = counts.count(
        conn,
        f"SELECT r.{_RECORD_KEY[source]} FROM {source} r JOIN taxon t USING (taxid) {where}",
        params,
    )
    sql, sql_params = _records_sql(source, within_path, keys, after, limit + 1)
    return total, _fetch_page(conn, sql, sql_params, keys, after, limit, ordering)


def _fetch_page(
    conn: psycopg.Connection, sql: str, params: Sequence[object], keys: Sequence[Key],
    after: Cursor | None, limit: int, ordering: str,
) -> Page[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, params).fetchall()
    key_names = [f"k{i}" for i in range(len(keys))]
    keys_of = [[row.pop(k) for k in key_names] for row in rows]
    return page(rows, keys_of, limit=limit, cursor=after, ordering=ordering)


@dataclass(frozen=True, slots=True)
class AssemblyFilter:
    """The assemblies a list holds: those on or below ``within_path`` (every one when
    None) that meet each condition given. With ``best_per_species``, only the
    first of each species among them in the recommended order."""

    within: int | None = None
    within_path: str | None = None
    levels: Sequence[str] = ()  # keys of ASSEMBLY_LEVELS
    reference: bool = False
    ebp_standard: bool = False
    min_contig_n50: int | None = None
    best_per_species: bool = False


def _is_reference(a: str) -> str:
    return f"COALESCE({a}.refseq_category = 'reference genome', false)"


def _meets_ebp(a: str) -> str:
    return (
        f"COALESCE({a}.contig_n50 >= {EBP_MIN_CONTIG_N50} "
        f"AND {a}.scaffold_n50 >= {EBP_MIN_SCAFFOLD_N50}, false)"
    )


def _level_rank(a: str) -> str:
    """0 for the most complete level, then up; a missing level last."""
    whens = " ".join(f"WHEN '{v}' THEN {i}" for i, v in enumerate(ASSEMBLY_LEVELS.values()))
    return f"CASE {a}.assembly_level {whens} ELSE {len(ASSEMBLY_LEVELS)} END"


def _assembly_where(f: AssemblyFilter) -> tuple[str, list[object]]:
    where: list[str] = []
    params: list[object] = []
    if f.within_path is not None:
        where.append("t.path <@ %s::ltree")
        params.append(f.within_path)
    if f.levels:
        where.append("r.assembly_level = ANY(%s)")
        params.append([ASSEMBLY_LEVELS[_identifier(level, ASSEMBLY_LEVELS)] for level in f.levels])
    if f.reference:
        where.append(_is_reference("r"))
    if f.ebp_standard:
        where.append(_meets_ebp("r"))
    if f.min_contig_n50 is not None:
        where.append("r.contig_n50 >= %s")
        params.append(f.min_contig_n50)
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


def _assembly_keys(sort: str, descending: bool) -> list[Key]:
    """The keys of an assembly sort, over the columns of ``_assembly_candidates``.
    ``recommended``: reference genomes first, then the most complete level, then
    the longest contig N50."""
    sort = _identifier(sort, [s.value for s in AssemblySort])
    if sort == "recommended":
        return [
            Key("is_reference", "boolean", descending),
            Key("level_rank", "integer", not descending),
            Key("(contig_n50 IS NULL)", "boolean"),
            Key("contig_n50", "bigint", descending),
            Key("id", "text"),
        ]
    return [
        Key(f"({sort} IS NULL)", "boolean"),
        Key(sort, _RECORD_SORT_TYPES[sort], descending),
        Key("id", "text"),
    ]


def _assembly_candidates(f: AssemblyFilter) -> tuple[str, list[object]]:
    """CTEs ending in ``c``: one row per assembly the list holds (per species with
    ``best_per_species``) with the columns its keys read."""
    where, params = _assembly_where(f)
    cols = (
        "r.assembly_accession AS id, r.contig_n50, r.scaffold_n50, "
        "r.total_sequence_length, r.release_date, "
        f"{_is_reference('r')} AS is_reference, {_level_rank('r')} AS level_rank"
    )
    source = f"FROM assembly r JOIN taxon t USING (taxid) {where}"
    if not f.best_per_species:
        return f"c AS (SELECT {cols} {source})", params
    best = ", ".join(
        f"{k.sql} {'DESC' if k.descending else 'ASC'}" for k in _assembly_keys("recommended", True)
    )
    per_species = (
        f"m AS (SELECT {cols}, r.species_taxid AS species {source}), "
        "c AS (SELECT DISTINCT ON (species) m.*, "
        "count(*) OVER (PARTITION BY species) AS species_assemblies "
        f"FROM m ORDER BY species, {best})"
    )
    return per_species, params


def _assemblies_sql(
    f: AssemblyFilter, sort: str, descending: bool, *, after: Cursor | None, limit: int | None
) -> tuple[str, list[object]]:
    """The assemblies of ``f`` in the order of ``sort``, as response rows followed by
    their key values k0, k1, ...: the page after (or before) ``after`` when ``limit``
    is set, else every one."""
    keys = _assembly_keys(sort, descending)
    candidates, params = _assembly_candidates(f)
    beyond_sql, beyond_params = beyond(keys, after) if after else ("TRUE", [])
    backward = after is not None and after.backward
    per_species = "species_assemblies, " if f.best_per_species else ""
    sql = (
        f"WITH {candidates}, "
        f"p AS (SELECT * FROM (SELECT id, {per_species}{key_columns(keys)} FROM c) q "
        f"WHERE {beyond_sql} ORDER BY {order_by(keys, backward=backward)} "
        f"{'LIMIT %s' if limit is not None else ''}) "
        f"SELECT {_ASSEMBLY_RECORD_SELECT}, "
        f"{_meets_ebp('a')} AS ebp_standard, a.annotations, a.best_busco, "
        f"{'p.species_assemblies' if f.best_per_species else 'NULL::bigint AS species_assemblies'}, "
        f"{', '.join(f'p.k{i}' for i in range(len(keys)))} "
        "FROM p JOIN assembly a ON a.assembly_accession = p.id JOIN taxon t ON t.taxid = a.taxid "
        f"ORDER BY {order_by(keys, backward=backward, table='p')}"
    )
    return sql, [*params, *beyond_params, *([limit] if limit is not None else [])]


def list_assemblies(
    conn: psycopg.Connection,
    f: AssemblyFilter,
    *,
    sort: str,
    descending: bool,
    limit: int,
    cursor: str | None,
) -> tuple[int, Page[dict]]:
    """One page of the assemblies of ``f``, as dicts keyed by the response-model
    fields, with the number of rows the list holds (species, with
    ``best_per_species``). Raises ``InvalidCursor`` for a cursor of another ordering."""
    keys = _assembly_keys(sort, descending)
    ordering = f"assembly:{sort}:{'desc' if descending else 'asc'}"
    after = decode_cursor(cursor, ordering=ordering, keys=keys) if cursor else None
    where, params = _assembly_where(f)
    unit = "DISTINCT r.species_taxid" if f.best_per_species else "r.assembly_accession"
    total = counts.count(
        conn, f"SELECT {unit} FROM assembly r JOIN taxon t USING (taxid) {where}", params
    )
    sql, sql_params = _assemblies_sql(f, sort, descending, after=after, limit=limit + 1)
    return total, _fetch_page(conn, sql, sql_params, keys, after, limit, ordering)


def _record_cell(value: object) -> str:
    """One TSV cell of a record: empty when missing, lists comma-separated."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return _tsv_cell(",".join(map(str, value)))
    return _tsv_cell(value)


def iter_records_tsv(
    pool: ConnectionPool, sql: str, params: Sequence[object], *, n_keys: int, batch_rows: int
) -> Iterator[str]:
    """Stream the rows of a record query built with ``limit=None`` as TSV: a header of
    its column names, then one chunk per ``batch_rows`` rows, without the trailing
    ``n_keys`` sort-key columns. Like ``iter_report_tsv``, it holds one pooled
    connection and a server-side cursor for the whole stream."""
    with pool.connection() as conn, conn.cursor(name="records") as cur:
        # A cursor is planned for reading its first tenth, which favours nested loops
        # that start fast but make a full download minutes long; this one reads it all.
        conn.execute("SET LOCAL cursor_tuple_fraction = 1")
        cur.execute(sql, params)
        rows = cur.fetchmany(batch_rows)
        width = len(cur.description) - n_keys
        yield "\t".join(col.name for col in cur.description[:width]) + "\n"
        while rows:
            yield "".join("\t".join(_record_cell(v) for v in row[:width]) + "\n" for row in rows)
            rows = cur.fetchmany(batch_rows)


def assemblies_report_sql(
    f: AssemblyFilter, *, sort: str, descending: bool
) -> tuple[str, list[object], int]:
    """Every assembly ``/assemblies`` lists for ``f`` and ``sort``, for
    ``iter_records_tsv``: the SQL, its parameters and the number of key columns."""
    sql, params = _assemblies_sql(f, sort, descending, after=None, limit=None)
    return sql, params, len(_assembly_keys(sort, descending))


def records_report_sql(
    source: str, within_path: str | None, *, sort: str, descending: bool
) -> tuple[str, list[object], int]:
    """Every record ``list_records`` pages through, for ``iter_records_tsv``."""
    keys = _record_keys(source, sort, descending)
    sql, params = _records_sql(source, within_path, keys, None, None)
    return sql, params, len(keys)


def _clade_stats(
    conn: psycopg.Connection, taxids: Sequence[int]
) -> dict[int, dict[str, float | None]]:
    """QUALITY_STATS of the given clades, computed at build time over the records on
    or below each (``clade_stats``), keyed by taxid. Clades without records are
    absent. Callers bound ``taxids`` to one page."""
    rows = conn.execute(
        f"SELECT taxid, {', '.join(QUALITY_KEYS)} FROM clade_stats WHERE taxid = ANY(%s)",
        (list(taxids),),
    ).fetchall()
    return {
        row[0]: {
            k: (float(v) if v is not None else None)
            for k, v in zip(QUALITY_KEYS, row[1:], strict=True)
        }
        for row in rows
    }


def fetch_quality_for_taxids(
    conn: psycopg.Connection, taxids: Sequence[int]
) -> dict[int, dict[str, float | None]]:
    """QUALITY_STATS over each given clade's subtree, keyed by taxid; every
    requested taxid is present (all-``None`` when it has no records). At most
    ``MAX_PAGE`` taxids, a page of ``/taxons/stats``."""
    if len(taxids) > MAX_PAGE:
        raise ValueError(f"at most {MAX_PAGE} taxids, got {len(taxids)}")
    all_keys = [q.key for q in QUALITY_STATS]
    result: dict[int, dict[str, float | None]] = {
        int(t): {k: None for k in all_keys} for t in taxids
    }
    if taxids:
        result.update(_clade_stats(conn, taxids))
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
    ``/taxons/aggregates``, and what the groups file names for ``/config``."""
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
