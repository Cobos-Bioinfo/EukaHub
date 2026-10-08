"""How the build writes the taxonomy."""

from __future__ import annotations

from eukahub_pipeline.build import _taxon_copy_rows
from eukahub_pipeline.taxdump import build_paths


def test_taxon_rows_are_written_with_each_subtree_together():
    # NCBI's file order mixes subtrees; 27590 is a sibling whose path starts like 2759's.
    nodes = {
        9606: (2759, "species"),
        1: (1, "no rank"),
        27590: (131567, "genus"),
        2759: (131567, "domain"),
        131567: (1, "no rank"),
        33154: (2759, "clade"),
        9605: (33154, "genus"),
    }
    paths = build_paths({t: parent for t, (parent, _) in nodes.items()})
    written = [row[4] for row in _taxon_copy_rows(nodes, {}, paths)]
    assert written == sorted(paths.values())
    inside = [p == paths[2759] or p.startswith(paths[2759] + ".") for p in written]
    first, last = inside.index(True), len(inside) - inside[::-1].index(True)
    assert all(inside[first:last])
