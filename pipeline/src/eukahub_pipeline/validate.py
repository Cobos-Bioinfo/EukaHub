"""Compare the new clade_features rollups against the old Euka-Survey numbers.

Exact matches aren't expected — the fresh taxdump post-dates the old build, so
the taxonomy has drifted slightly. Small deltas validate the port; large ones
signal a bug.
"""

from __future__ import annotations

import logging
import sqlite3

import psycopg

log = logging.getLogger("eukahub.validate")

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


def validate(conn: psycopg.Connection, leaf_sqlite: str) -> None:
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
