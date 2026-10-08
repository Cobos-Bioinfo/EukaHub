"""Post-build validation: hard invariant gates + an optional parity printout.

Three jobs:

1. ``check_invariants`` — self-contained assertions on the freshly-loaded serving
   DB that **raise** on failure, so a broken rebuild (empty tables, a botched
   rollup, a source field that came back empty) never gets stamped or shipped.
   This is the gate the automated rebuild relies on; it needs nothing but the
   serving DB.

2. ``release_counts`` and ``check_against_previous`` — the key counts of a build,
   and the gate that fails when one fell sharply since the previous Release: a
   partial download from a source is self-consistent, so only a comparison
   catches it.

3. ``validate`` — runs the invariants, then, *if* the old Euka-Survey SQLite is
   present, prints the parity comparison (species counts + total RNA-Seq runs) it
   always did. In CI / the scheduled rebuild that file is absent, so the parity
   step is skipped rather than crashing.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
from collections.abc import Mapping

import psycopg
from eukahub_core.metrics import (
    COVERAGE_KEYS,
    METRICS,
    QUALITY_KEYS,
    QUALITY_STATS,
    TOTAL_KEYS,
)
from eukahub_core.taxonomy import EUKARYOTA_TAXID, INFORMAL_SPECIES_RANK

log = logging.getLogger("eukahub.validate")

COMMON = [
    (EUKARYOTA_TAXID, "Eukaryota"),
    (33208, "Metazoa"),
    (40674, "Mammalia"),
    (9443, "Primates"),
    (4751, "Fungi"),
    (33090, "Viridiplantae"),
]

# Order matters — index 0 = n_rows, index 7 = s_rna (used in the printout).
_COLS = ("n_rows", "c_ass", "c_ann", "c_rna", "c_lng", "s_ass", "s_ann", "s_rna", "s_lng")


# The smallest share of records that must carry each field. A field the source
# renames or stops sending comes back empty on every record, far below these.
MIN_FILLED: dict[tuple[str, str], float] = {
    ("assembly", "assembly_level"): 0.9,
    ("assembly", "contig_n50"): 0.9,
    ("assembly", "total_sequence_length"): 0.9,
    ("annotation", "protein_coding_count"): 0.9,
    ("annotation", "busco_complete"): 0.5,
}

# The largest drop of a key count since the previous Release, as a share, before
# the build is refused. Month to month the counts grow or move by a few percent; a
# truncated download loses far more.
MAX_DROP = 0.1


class DataValidationError(Exception):
    """Raised when a post-build invariant fails — the rebuild is not shippable."""


def check_invariants(conn: psycopg.Connection) -> None:
    """Assert the freshly-built serving DB is internally consistent, raising
    ``DataValidationError`` on the first violation.

    The checks are deliberately structural (not pinned magic numbers), so they
    hold across rebuilds as the sources drift: non-empty tables, the species
    universe matches the rollup, the totals match the record tables, no informal
    species is kept without data, coverage never exceeds the species count, the
    additive assembly-composition split reconciles with the assembly total, every
    resource has data, one row per assembly, the fields the stats read are filled,
    and the per-clade quality stats cover the clades with records and match them.
    """
    with conn.cursor() as cur:

        def scalar(sql: str, params: tuple = ()) -> int:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else 0

        # 1. Nothing came back empty — the most common "the fetch silently failed"
        #    failure mode. Every core table must have rows.
        for table in ("taxon", "clade_features", "clade_stats", "assembly", "annotation"):
            n = scalar(f"SELECT count(*) FROM {table}")
            if n == 0:
                raise DataValidationError(f"{table} is empty after build")
            log.info("invariant: %-16s %10d rows", table, n)

        euk_path, euk = _eukaryota(cur)

        # 2. Eukaryota's species universe (n_rows) equals a direct count of
        #    rank='species' under it — the pipeline's key rollup invariant. The
        #    path is a literal: a subquery would make Postgres scan the whole
        #    path index, on the build runner and on every server that installs.
        euk_n_rows = euk["n_rows"]
        species_under_euk = scalar(
            "SELECT count(*) FROM taxon WHERE rank = 'species' AND path <@ %s::ltree",
            (euk_path,),
        )
        if euk_n_rows != species_under_euk:
            raise DataValidationError(
                f"Eukaryota n_rows ({euk_n_rows}) != species under Eukaryota "
                f"({species_under_euk})"
            )
        log.info("invariant: Eukaryota n_rows == species count (%d)", euk_n_rows)

        # 3. Every record counts at Eukaryota, whatever rank it is attached to, so
        #    its totals match the record tables.
        for table, total in (("assembly", "s_ass"), ("annotation", "s_ann")):
            records = scalar(f"SELECT count(*) FROM {table}")
            rolled = euk[total]
            if rolled != records:
                raise DataValidationError(
                    f"Eukaryota {total} ({rolled}) != {table} records ({records})"
                )
        log.info("invariant: Eukaryota totals match the record tables")

        # 4. Informal species are kept only when they carry data.
        empty_informal = scalar(
            "SELECT count(*) FROM taxon t LEFT JOIN clade_features f USING (taxid) "
            "WHERE t.rank = %s AND COALESCE(f.s_ass + f.s_ann + f.s_rna, 0) = 0",
            (INFORMAL_SPECIES_RANK,),
        )
        if empty_informal:
            raise DataValidationError(f"{empty_informal} informal species carry no data")

        # 5. Coverage never exceeds the species count, for any clade.
        bad = scalar(
            "SELECT count(*) FROM clade_features "
            "WHERE c_ass > n_rows OR c_ann > n_rows OR c_rna > n_rows OR c_lng > n_rows"
        )
        if bad:
            raise DataValidationError(f"{bad} clade rows have coverage > n_rows")

        # 6. Eukaryota's assembly-level split reconciles: the four buckets sum to
        #    at most s_ass (some assemblies carry no/unmapped level), and non-zero.
        level_sum = sum(
            euk[c] for c in ("n_ass_complete", "n_ass_chromosome", "n_ass_scaffold", "n_ass_contig")
        )
        s_ass = euk["s_ass"]
        if not (0 < level_sum <= s_ass):
            raise DataValidationError(
                f"Eukaryota composition split ({level_sum}) not in (0, s_ass={s_ass}]"
            )
        log.info("invariant: composition split %d <= s_ass %d", level_sum, s_ass)

        # 7. Every resource has data at Eukaryota: a source that returned nothing
        #    usable leaves its coverage at zero.
        empty = [m.card_title for m in METRICS if euk[m.coverage_key] == 0]
        if empty:
            raise DataValidationError(f"no species has data for: {', '.join(empty)}")

        # 8. One row per assembly number: a GenBank assembly and its RefSeq copy,
        #    or two versions of one assembly, are counted once.
        repeated = scalar(
            "SELECT count(*) - count(DISTINCT split_part(split_part("
            "assembly_accession, '_', 2), '.', 1)) FROM assembly"
        )
        if repeated:
            raise DataValidationError(f"{repeated} assembly rows repeat an assembly number")

        # 9. The fields the quality stats and composition read are filled: a field
        #    a source renames comes back empty instead of failing the fetch.
        for (table, column), minimum in MIN_FILLED.items():
            cur.execute(f"SELECT avg(({column} IS NOT NULL)::int) FROM {table}")
            share = float(cur.fetchone()[0] or 0)
            if share < minimum:
                raise DataValidationError(
                    f"{table}.{column} is filled on {share:.0%} of rows (at least "
                    f"{minimum:.0%} expected): did the source rename the field?"
                )
        log.info("invariant: one row per assembly; source fields filled")

        # 10. Quality stats exist for exactly the clades with records on or below them.
        mismatched = scalar(
            "SELECT count(*) FROM clade_stats s "
            "FULL JOIN (SELECT taxid FROM clade_features WHERE s_ass + s_ann > 0) f "
            "USING (taxid) WHERE s.taxid IS NULL OR f.taxid IS NULL"
        )
        if mismatched:
            raise DataValidationError(
                f"{mismatched} clades have quality stats but no records, or the reverse"
            )

        # 11. The stored stats of the common clades equal Postgres' own aggregates
        #    over their records (absent clades are skipped: the CI slice lacks some).
        for taxid, name in COMMON:
            cur.execute("SELECT path::text FROM taxon WHERE taxid = %s", (taxid,))
            row = cur.fetchone()
            if row is None:
                continue
            expected = _stats_from_records(cur, row[0])
            cur.execute(
                f"SELECT {', '.join(QUALITY_KEYS)} FROM clade_stats WHERE taxid = %s", (taxid,)
            )
            stored = dict(zip(QUALITY_KEYS, cur.fetchone() or [None] * len(QUALITY_KEYS)))
            for key in QUALITY_KEYS:
                a, b = stored[key], expected[key]
                if (a is None) != (b is None) or (a is not None and not math.isclose(a, b)):
                    raise DataValidationError(f"{name} {key}: stored {a}, its records give {b}")
        log.info("invariant: clade_stats match their records")

    log.info("all invariants passed")


_EUKARYOTA_COLUMNS = (
    "n_rows",
    *COVERAGE_KEYS,
    *TOTAL_KEYS,
    "n_ass_complete",
    "n_ass_chromosome",
    "n_ass_scaffold",
    "n_ass_contig",
)


def _eukaryota(cur: psycopg.Cursor) -> tuple[str, dict[str, int]]:
    """Eukaryota's path and rollup row; a clear failure if either is missing."""
    cur.execute("SELECT path::text FROM taxon WHERE taxid = %s", (EUKARYOTA_TAXID,))
    row = cur.fetchone()
    if row is None:
        raise DataValidationError(f"Eukaryota ({EUKARYOTA_TAXID}) is not in the taxon table")
    path = row[0]
    cur.execute(
        f"SELECT {', '.join(_EUKARYOTA_COLUMNS)} FROM clade_features WHERE taxid = %s",
        (EUKARYOTA_TAXID,),
    )
    row = cur.fetchone()
    if row is None:
        raise DataValidationError(f"Eukaryota ({EUKARYOTA_TAXID}) has no clade_features row")
    return path, dict(zip(_EUKARYOTA_COLUMNS, row, strict=True))


def release_counts(conn: psycopg.Connection) -> dict[str, int]:
    """The counts a build is compared with the previous Release by: taxa, species,
    and for each resource the species with data and the records at Eukaryota,
    named like the TSV report's columns."""
    with conn.cursor() as cur:
        _path, euk = _eukaryota(cur)
        cur.execute("SELECT count(*) FROM taxon")
        taxa = cur.fetchone()[0]
    return {
        "taxa": taxa,
        "total_species": euk["n_rows"],
        **{m.tsv_count_column: euk[m.coverage_key] for m in METRICS},
        **{m.tsv_total_column: euk[m.total_key] for m in METRICS},
    }


def count_drops(
    current: Mapping[str, int], previous: Mapping[str, int], max_drop: float = MAX_DROP
) -> list[str]:
    """The counts that fell by more than ``max_drop`` since ``previous``, in words.
    A count only one side has (a metric added or removed since) is skipped."""
    return [
        f"{key} {previous[key]:,} -> {current[key]:,} "
        f"({(current[key] - previous[key]) / previous[key]:+.1%})"
        for key in current
        if key in previous and current[key] < previous[key] * (1 - max_drop)
    ]


def check_against_previous(
    current: Mapping[str, int], previous: Mapping[str, int], *, accept_drops: bool = False
) -> None:
    """Refuse a build whose key counts fell sharply since the previous Release, the
    sign of a partial download; ``accept_drops`` only logs them, for a drop a person
    has checked is real."""
    drops = count_drops(current, previous)
    if not drops:
        log.info("counts: none fell more than %.0f%% since the previous Release", MAX_DROP * 100)
        return
    listed = "; ".join(drops)
    message = f"counts fell more than {MAX_DROP:.0%} since the previous Release: {listed}"
    if not accept_drops:
        raise DataValidationError(message)
    log.warning("%s (accepted)", message)


def _stats_from_records(cur: psycopg.Cursor, path: str) -> dict[str, float | None]:
    """QUALITY_STATS over the records on or below ``path``, computed by Postgres."""
    out: dict[str, float | None] = {}
    for source in ("assembly", "annotation"):
        stats = [q for q in QUALITY_STATS if q.source == source]
        aggregates = ", ".join(
            f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {q.column})"
            if q.agg == "median"
            else f"max({q.column})"
            for q in stats
        )
        cur.execute(
            f"SELECT {aggregates} FROM {source} r JOIN taxon t USING (taxid) "
            "WHERE t.path <@ %s::ltree",
            (path,),
        )
        out |= dict(zip((q.key for q in stats), cur.fetchone(), strict=True))
    return out


def _old(sqlite_path: str) -> dict[int, tuple | None]:
    con = sqlite3.connect(str(sqlite_path))
    try:
        return {
            taxid: con.execute(
                f"SELECT {', '.join(_COLS)} FROM precomputed_clade_features WHERE taxid=?",
                (taxid,),
            ).fetchone()
            for taxid, _ in COMMON
        }
    finally:
        con.close()


def _new(conn: psycopg.Connection) -> dict[int, tuple | None]:
    out: dict[int, tuple | None] = {}
    with conn.cursor() as cur:
        for taxid, _ in COMMON:
            cur.execute(
                f"SELECT {', '.join(_COLS)} FROM clade_features WHERE taxid=%s", (taxid,)
            )
            out[taxid] = cur.fetchone()
    return out


def validate(conn: psycopg.Connection, leaf_sqlite: str | None = None) -> None:
    """Gate the build on the invariants, then print the Euka-Survey parity table
    when the old SQLite is available (skipped in CI / the scheduled rebuild)."""
    check_invariants(conn)

    if not leaf_sqlite or not os.path.exists(leaf_sqlite):
        log.info("parity check skipped (Euka-Survey leaf DB not present: %s)", leaf_sqlite)
        return

    old = _old(leaf_sqlite)
    new = _new(conn)
    print("\n=== Validation vs Euka-Survey (species count + total RNA-Seq runs) ===")
    print(
        f"{'taxid':>7} {'name':<13} {'n_rows old':>12} {'n_rows new':>12} {'Δ%':>6}"
        f" {'s_rna old':>12} {'s_rna new':>12}"
    )
    for taxid, name in COMMON:
        o, n = old[taxid], new.get(taxid)
        if o is None or n is None:
            print(f"{taxid:>7} {name:<13}  old={o} new={n}")
            continue
        delta = (n[0] - o[0]) / o[0] * 100 if o[0] else float("nan")
        print(
            f"{taxid:>7} {name:<13} {o[0]:>12,} {n[0]:>12,} {delta:>5.1f}%"
            f" {o[7]:>12,} {n[7]:>12,}"
        )
