"""Postgres COPY loaders for the read-only serving tables.

Serving is read-only and the dataset is rebuilt wholesale, so we TRUNCATE and
COPY rather than upsert. ``taxon`` is loaded before ``clade_features`` (which
references it).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import polars as pl
import psycopg

log = logging.getLogger("eukahub.load")


def load_taxon(conn: psycopg.Connection, rows: Iterable[tuple]) -> int:
    """COPY (taxid, name, rank, parent_id, path) rows into ``taxon``.

    The ``path`` element is a dot-separated taxid string — a valid ltree
    literal, parsed by the column's input function during COPY.
    """
    n = 0
    with conn.cursor() as cur:
        cur.execute("TRUNCATE taxon CASCADE")  # also clears clade_features (FK)
        with cur.copy("COPY taxon (taxid, name, rank, parent_id, path) FROM STDIN") as cp:
            for row in rows:
                cp.write_row(row)
                n += 1
    conn.commit()
    return n


def load_clade_features(conn: psycopg.Connection, clade: pl.DataFrame) -> int:
    """COPY the rollup DataFrame into ``clade_features`` (column order = df)."""
    cols = clade.columns
    with conn.cursor() as cur:
        with cur.copy(f"COPY clade_features ({', '.join(cols)}) FROM STDIN") as cp:
            for row in clade.iter_rows():
                cp.write_row(row)
    conn.commit()
    return clade.height
