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

from eukahub_pipeline.fetch_annotations import ANNOTATION_COLUMNS
from eukahub_pipeline.fetch_assemblies import ASSEMBLY_COLUMNS

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
    with (
        conn.cursor() as cur,
        cur.copy(f"COPY clade_features ({', '.join(cols)}) FROM STDIN") as cp,
    ):
        for row in clade.iter_rows():
            cp.write_row(row)
    conn.commit()
    return clade.height


def _copy_frame(
    conn: psycopg.Connection, table: str, columns: tuple[str, ...], df: pl.DataFrame
) -> int:
    """TRUNCATE ``table`` and COPY ``df`` into it, selecting ``columns`` in order.

    psycopg adapts each Python value during COPY — list columns (e.g. an
    assembly's ``bioprojects``) become Postgres arrays and ``YYYY-MM-DD`` strings
    become DATEs, matching the per-record schema.
    """
    frame = df.select(list(columns))
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {table}")
        with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
            for row in frame.iter_rows():
                cp.write_row(row)
    conn.commit()
    return frame.height


def load_dataset_meta(
    conn: psycopg.Connection,
    *,
    taxon_count: int,
    assembly_count: int,
    annotation_count: int,
    clade_count: int,
) -> None:
    """Stamp the single ``dataset_meta`` row with ``built_at = now()`` (UTC) and
    the loaded record counts.

    Called last, so the timestamp marks a fully-loaded dataset; a dump/restore
    then carries the stamp with the data. TRUNCATE + INSERT keeps the one-row
    invariant (the fixed ``id = TRUE`` primary key also guards it).
    """
    with conn.cursor() as cur:
        cur.execute("TRUNCATE dataset_meta")
        cur.execute(
            "INSERT INTO dataset_meta "
            "(built_at, taxon_count, assembly_count, annotation_count, clade_count) "
            "VALUES (now(), %s, %s, %s, %s)",
            (taxon_count, assembly_count, annotation_count, clade_count),
        )
    conn.commit()


def load_assembly(conn: psycopg.Connection, df: pl.DataFrame) -> int:
    """COPY per-assembly rows (``fetch_assemblies``) into ``assembly``."""
    return _copy_frame(conn, "assembly", ASSEMBLY_COLUMNS, df)


def load_annotation(conn: psycopg.Connection, df: pl.DataFrame) -> int:
    """COPY per-annotation rows (``fetch_annotations``) into ``annotation``."""
    return _copy_frame(conn, "annotation", ANNOTATION_COLUMNS, df)
