"""How the build writes the taxonomy and prepares the sources."""

from __future__ import annotations

import polars as pl
from eukahub_pipeline.build import _remap_merged, _studies_to_keep, _taxon_copy_rows
from eukahub_pipeline.load import TAXON_COLUMNS
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
    path = TAXON_COLUMNS.index("path")
    written = [row[path] for row in _taxon_copy_rows(nodes, {}, {}, paths)]
    assert written == sorted(paths.values())
    inside = [p == paths[2759] or p.startswith(paths[2759] + ".") for p in written]
    first, last = inside.index(True), len(inside) - inside[::-1].index(True)
    assert all(inside[first:last])


def test_taxon_rows_carry_the_common_name():
    nodes = {1: (1, "no rank"), 9606: (1, "species")}
    rows = {r[0]: dict(zip(TAXON_COLUMNS, r)) for r in _taxon_copy_rows(
        nodes, {9606: "Homo sapiens"}, {9606: "human"}, build_paths({1: 1, 9606: 1})
    )}
    assert rows[9606]["common_name"] == "human"
    assert rows[1]["common_name"] is None


def test_rows_on_a_merged_taxid_move_to_its_current_one():
    frame = pl.DataFrame({"taxid": [12, 9606, 30]})
    assert _remap_merged(frame, {12: 74109, 30: 29}, "test")["taxid"].to_list() == [74109, 9606, 29]


def test_the_studies_kept_are_those_with_runs_and_their_parents():
    studies = pl.DataFrame(
        {
            "study_accession": ["PRJEB42931", "PRJEB42945", "PRJNA312255", "PRJEB9"],
            "title": ["reads", "umbrella", "EBP", "unrelated"],
            "parents": [["PRJEB42945", "PRJNA312255"], [], [], []],
        }
    )
    run_groups = pl.DataFrame({"study_accession": ["PRJEB42931", None, "PRJEB0"]})
    kept = _studies_to_keep(studies, run_groups)["study_accession"].to_list()
    assert sorted(kept) == ["PRJEB42931", "PRJEB42945", "PRJNA312255"]
