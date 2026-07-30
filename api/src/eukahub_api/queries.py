"""SQL read functions over the serving tables.

Returns core domain objects (``CladeMetadata``) rather than raw rows, so the
metric-percentage logic stays in ``eukahub_core`` and is shared with the
pipeline. The column list is built from the metric config, mirroring
Euka-Survey's ``_SQL_COLUMNS`` discipline: SELECT order == CladeMetadata
field order, guarded by a test.
"""

from __future__ import annotations

import psycopg
from eukahub_core.metrics import COVERAGE_KEYS, TOTAL_KEYS, CladeMetadata

# n_rows, then c_* (COVERAGE_KEYS), then s_* (TOTAL_KEYS) — the exact tail of
# CladeMetadata's constructor after taxid.
_FEATURE_COLS: tuple[str, ...] = ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS

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
