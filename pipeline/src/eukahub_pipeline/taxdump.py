"""Parse an NCBI taxdump into rows for the ``taxon`` table. No ETE3.

Input: an unpacked taxdump directory containing ``nodes.dmp`` and
``names.dmp`` (from ftp.ncbi.nih.gov/pub/taxonomy/taxdump.tar.gz).

Output: ``TaxonRow(taxid, name, rank, parent_id, path)`` where ``path`` is a
materialized ``ltree`` lineage — the root->node chain of taxids joined by
dots (e.g. Homo sapiens -> ``1.131567.2759.….9606``). Numeric ltree labels
are valid, so taxids are used verbatim.

Phase 1 streams these rows into Postgres via COPY, then the roll-up sums
features up each lineage. The parent-walk that builds ``path`` is memoized,
so the whole tree (~2.5M nodes) is a single linear pass.

dmp format: fields are separated by ``\\t|\\t`` and each row ends with
``\\t|`` (before the newline).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TaxonRow:
    taxid: int
    name: str
    rank: str
    parent_id: int
    path: str


def _iter_dmp(path: Path) -> Iterator[list[str]]:
    """Yield each dmp row as a list of already-split field strings."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            line = line.removesuffix("\t|")
            yield line.split("\t|\t")


def parse_nodes(nodes_path: Path) -> dict[int, tuple[int, str]]:
    """Map ``taxid -> (parent_taxid, rank)`` from ``nodes.dmp``.

    nodes.dmp columns: tax_id | parent tax_id | rank | ...
    """
    nodes: dict[int, tuple[int, str]] = {}
    for fields in _iter_dmp(nodes_path):
        taxid = int(fields[0])
        parent = int(fields[1])
        rank = fields[2]
        nodes[taxid] = (parent, rank)
    return nodes


def parse_names(names_path: Path) -> dict[int, str]:
    """Map ``taxid -> scientific name`` from ``names.dmp``.

    names.dmp columns: tax_id | name_txt | unique name | name class.
    Only the "scientific name" class is kept.
    """
    names: dict[int, str] = {}
    for fields in _iter_dmp(names_path):
        if fields[3] == "scientific name":
            names[int(fields[0])] = fields[1]
    return names


def build_paths(parents: dict[int, int]) -> dict[int, str]:
    """Build the materialized ltree ``path`` for every taxid.

    Walks each node up to the root, memoizing every path seen so shared
    ancestors are computed once. The NCBI root (taxid 1) is its own parent;
    an orphan whose parent is missing is treated as a root.
    """
    path_cache: dict[int, str] = {}

    def path_for(taxid: int) -> str:
        cached = path_cache.get(taxid)
        if cached is not None:
            return cached

        # Walk up until we hit a cached ancestor or a root (self-parent /
        # missing parent), collecting the uncached chain on the way.
        chain: list[int] = []
        node = taxid
        base = ""
        while True:
            cached_anc = path_cache.get(node)
            if cached_anc is not None:
                base = cached_anc
                break
            chain.append(node)
            parent = parents.get(node)
            if parent is None or parent == node:
                base = ""  # `node` is a root
                break
            node = parent

        # Extend downward from the cached/root base, filling the cache.
        prefix = base
        for t in reversed(chain):
            prefix = f"{prefix}.{t}" if prefix else str(t)
            path_cache[t] = prefix
        return path_cache[taxid]

    for taxid in parents:
        path_for(taxid)
    return path_cache


def iter_taxon_rows(taxdump_dir: str | Path) -> Iterator[TaxonRow]:
    """Yield a ``TaxonRow`` for every node in the taxdump directory."""
    d = Path(taxdump_dir)
    nodes = parse_nodes(d / "nodes.dmp")
    names = parse_names(d / "names.dmp")
    parents = {taxid: parent for taxid, (parent, _) in nodes.items()}
    paths = build_paths(parents)

    for taxid, (parent, rank) in nodes.items():
        yield TaxonRow(
            taxid=taxid,
            name=names.get(taxid, str(taxid)),
            rank=rank,
            parent_id=parent,
            path=paths[taxid],
        )
