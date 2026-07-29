"""Unit tests for the taxdump parser + ltree path builder.

Uses a tiny hand-written taxdump so the core algorithm is validated without
the ~400 MB download or a running database.
"""

from pathlib import Path

from eukahub_pipeline.taxdump import (
    build_paths,
    iter_taxon_rows,
    parse_names,
    parse_nodes,
)

# A toy tree:  1 (root) -> 131567 -> 2759 (Eukaryota) -> 9606 (leaf)
#              1 -> 10239 (a second child of root)
_NODES_DMP = (
    "1\t|\t1\t|\tno rank\t|\n"
    "131567\t|\t1\t|\tno rank\t|\n"
    "2759\t|\t131567\t|\tsuperkingdom\t|\n"
    "9606\t|\t2759\t|\tspecies\t|\n"
    "10239\t|\t1\t|\tsuperkingdom\t|\n"
)

_NAMES_DMP = (
    "1\t|\troot\t|\t\t|\tscientific name\t|\n"
    "2759\t|\tEukaryota\t|\t\t|\tscientific name\t|\n"
    "2759\t|\tEucarya\t|\t\t|\tsynonym\t|\n"
    "9606\t|\tHomo sapiens\t|\t\t|\tscientific name\t|\n"
)


def _write_taxdump(tmp_path: Path) -> Path:
    (tmp_path / "nodes.dmp").write_text(_NODES_DMP, encoding="utf-8")
    (tmp_path / "names.dmp").write_text(_NAMES_DMP, encoding="utf-8")
    return tmp_path


def test_parse_nodes(tmp_path: Path) -> None:
    d = _write_taxdump(tmp_path)
    nodes = parse_nodes(d / "nodes.dmp")
    assert nodes[9606] == (2759, "species")
    assert nodes[1] == (1, "no rank")


def test_parse_names_keeps_only_scientific(tmp_path: Path) -> None:
    d = _write_taxdump(tmp_path)
    names = parse_names(d / "names.dmp")
    assert names[2759] == "Eukaryota"  # synonym "Eucarya" ignored
    assert names[9606] == "Homo sapiens"


def test_build_paths() -> None:
    parents = {1: 1, 131567: 1, 2759: 131567, 9606: 2759, 10239: 1}
    paths = build_paths(parents)
    assert paths[1] == "1"
    assert paths[2759] == "1.131567.2759"
    assert paths[9606] == "1.131567.2759.9606"
    assert paths[10239] == "1.10239"


def test_iter_taxon_rows(tmp_path: Path) -> None:
    d = _write_taxdump(tmp_path)
    rows = {r.taxid: r for r in iter_taxon_rows(d)}

    human = rows[9606]
    assert human.name == "Homo sapiens"
    assert human.rank == "species"
    assert human.parent_id == 2759
    assert human.path == "1.131567.2759.9606"

    # A taxid missing a scientific name falls back to its stringified id.
    assert rows[131567].name == "131567"
