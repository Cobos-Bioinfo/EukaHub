"""Post-build validation: hard invariant gates + an optional parity printout.

Two jobs:

1. ``check_invariants`` — self-contained assertions on the freshly-loaded serving
   DB that **raise** on failure, so a broken rebuild (empty tables, a botched
   rollup) never gets stamped or shipped. This is the gate the automated rebuild
   relies on; it needs nothing but the serving DB.

2. ``validate`` — runs the invariants, then, *if* the old Euka-Survey SQLite is
   present, prints the parity comparison (species counts + total RNA-Seq runs) it
   always did. In CI / the scheduled rebuild that file is absent, so the parity
   step is skipped rather than crashing.
"""

from __future__ import annotations

import logging
import os
import sqlite3

import psycopg

log = logging.getLogger("eukahub.validate")

EUKARYOTA_TAXID = 2759

COMMON = [
    (2759, "Eukaryota"),
    (33208, "Metazoa"),
    (40674, "Mammalia"),
    (9443, "Primates"),
    (4751, "Fungi"),
    (33090, "Viridiplantae"),
]

# Order matters — index 0 = n_rows, index 7 = s_rna (used in the printout).
_COLS = ("n_rows", "c_ass", "c_ann", "c_rna", "c_lng", "s_ass", "s_ann", "s_rna", "s_lng")


class DataValidationError(Exception):
    """Raised when a post-build invariant fails — the rebuild is not shippable."""


def check_invariants(conn: psycopg.Connection) -> None:
    """Assert the freshly-built serving DB is internally consistent, raising
    ``DataValidationError`` on the first violation.

    The checks are deliberately structural (not pinned magic numbers), so they
    hold across rebuilds as the sources drift: non-empty tables, the species
    universe matches the rollup, coverage never exceeds the species count, and the
    additive assembly-composition split reconciles with the assembly total.
    """
    with conn.cursor() as cur:

        def scalar(sql: str, params: tuple = ()) -> int:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else 0

        # 1. Nothing came back empty — the most common "the fetch silently failed"
        #    failure mode. Every core table must have rows.
        for table in ("taxon", "clade_features", "assembly", "annotation"):
            n = scalar(f"SELECT count(*) FROM {table}")
            if n == 0:
                raise DataValidationError(f"{table} is empty after build")
            log.info("invariant: %-16s %10d rows", table, n)

        # 2. Eukaryota's species universe (n_rows) equals a direct count of
        #    rank='species' under it — the pipeline's key rollup invariant.
        euk_n_rows = scalar(
            "SELECT n_rows FROM clade_features WHERE taxid = %s", (EUKARYOTA_TAXID,)
        )
        species_under_euk = scalar(
            "SELECT count(*) FROM taxon WHERE rank = 'species' "
            "AND path <@ (SELECT path FROM taxon WHERE taxid = %s)",
            (EUKARYOTA_TAXID,),
        )
        if euk_n_rows != species_under_euk:
            raise DataValidationError(
                f"Eukaryota n_rows ({euk_n_rows}) != species under Eukaryota "
                f"({species_under_euk})"
            )
        log.info("invariant: Eukaryota n_rows == species count (%d)", euk_n_rows)

        # 3. Coverage never exceeds the species count, for any clade.
        bad = scalar(
            "SELECT count(*) FROM clade_features "
            "WHERE c_ass > n_rows OR c_ann > n_rows OR c_rna > n_rows OR c_lng > n_rows"
        )
        if bad:
            raise DataValidationError(f"{bad} clade rows have coverage > n_rows")

        # 4. Eukaryota's assembly-level split reconciles: the four buckets sum to
        #    at most s_ass (some assemblies carry no/unmapped level), and non-zero.
        cur.execute(
            "SELECT n_ass_complete + n_ass_chromosome + n_ass_scaffold + n_ass_contig, "
            "s_ass FROM clade_features WHERE taxid = %s",
            (EUKARYOTA_TAXID,),
        )
        level_sum, s_ass = cur.fetchone()
        if not (0 < level_sum <= s_ass):
            raise DataValidationError(
                f"Eukaryota composition split ({level_sum}) not in (0, s_ass={s_ass}]"
            )
        log.info("invariant: composition split %d <= s_ass %d", level_sum, s_ass)

    log.info("all invariants passed")


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
