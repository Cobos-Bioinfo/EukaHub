"""Unit test for the Polars rollup on a toy tree — validates the fan-out and
the per-metric derivations without a database or the real taxdump.
"""

import polars as pl
from eukahub_pipeline.rollup import rollup_from_frames


def test_rollup_from_frames() -> None:
    taxon = pl.DataFrame(
        {
            "taxid": [1, 2759, 9606, 10090],
            "rank": ["no rank", "superkingdom", "species", "species"],
            "path": ["1", "1.2759", "1.2759.9606", "1.2759.10090"],
        }
    )
    features = pl.DataFrame(
        {
            "taxid": [9606, 10090],
            "short": [5, 0],
            "long": [0, 3],
            "ass": [2, 1],
            "ann": [1, 0],
        }
    )
    out = {r[0]: r for r in rollup_from_frames(taxon, features).iter_rows()}

    # cols: taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng
    assert out[9606] == (9606, 1, 1, 1, 1, 0, 2, 1, 5, 0)
    assert out[10090] == (10090, 1, 1, 0, 1, 1, 1, 0, 3, 3)
    # Ancestors accumulate both species:
    assert out[2759] == (2759, 2, 2, 1, 2, 1, 3, 1, 8, 3)
    assert out[1] == (1, 2, 2, 1, 2, 1, 3, 1, 8, 3)
    # A non-species node with no species leaf never appears as a rollup row.
    assert 9605 not in out


def test_rollup_infraspecific_rows_not_counted_upward() -> None:
    """Below-species taxa get their own directly-attached rows (n_rows=1) but are
    never rolled into an ancestor — the species rollup stays species-only."""
    taxon = pl.DataFrame(
        {
            "taxid": [1, 2759, 9606, 63221, 2000000],
            "rank": ["no rank", "superkingdom", "species", "subspecies", "strain"],
            "path": [
                "1",
                "1.2759",
                "1.2759.9606",
                "1.2759.9606.63221",
                "1.2759.9606.63221.2000000",
            ],
        }
    )
    features = pl.DataFrame(
        {
            "taxid": [9606, 63221, 2000000],
            "short": [5, 0, 1],
            "long": [0, 0, 0],
            "ass": [2, 3, 1],
            "ann": [1, 0, 0],
        }
    )
    out = {r[0]: r for r in rollup_from_frames(taxon, features).iter_rows()}

    # cols: taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng
    # The species keeps only its OWN species-level features (subspecies dropped):
    assert out[9606] == (9606, 1, 1, 1, 1, 0, 2, 1, 5, 0)
    # Ancestors count ONLY the one species — the subspecies + strain add nothing:
    assert out[2759] == (2759, 1, 1, 1, 1, 0, 2, 1, 5, 0)
    # Below-species taxa each get their own row: n_rows=1, directly-attached only.
    assert out[63221] == (63221, 1, 1, 0, 0, 0, 3, 0, 0, 0)
    assert out[2000000] == (2000000, 1, 1, 0, 1, 0, 1, 0, 1, 0)
