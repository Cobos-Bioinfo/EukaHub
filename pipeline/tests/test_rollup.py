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
