"""Placeholder taxa: species-rank names that are not formal species, and the
containers that hold them ("environmental samples", "unclassified Homo").

NCBI files every sequenced organism under a taxid, so more than half of its
eukaryote species-rank taxa are placeholders ("Homo sp.", "uncultured
eukaryote", "Acropora cf. tenuis"). Counted as species they would dilute every
coverage figure, so the build drops the ones without data and relabels the rest.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from eukahub_core.taxonomy import INFORMAL_SPECIES_RANK, SPECIES_RANK, UNIT_RANKS

# Lifemap's filters for placeholder names.
_PLACEHOLDER = re.compile(
    r"unclassified|uncultured|unidentified|environmental| sp\.", re.IGNORECASE
)
# "Genus epithet", allowing a bracketed genus ("[Candida] boidinii"), a hyphenated
# genus ("Pseudo-nitzschia") and a hybrid sign ("Mentha x piperita", "x Festulolium braunii").
_BINOMIAL = re.compile(
    r"(?:[x×] )?(?:\[[A-Z][a-z]+\]|[A-Z][a-z]+(?:-[A-Z]?[a-z]+)?) (?:× ?|x )?[a-z][a-z-]+"
)
# A note NCBI appends to some formal names: an author, "(nom. inval.)", "(in: crustaceans)".
_TRAILING_NOTE = re.compile(r" \(.*\)$")

BELOW_SPECIES_RANKS = frozenset(
    {
        "subspecies",
        "varietas",
        "subvariety",
        "forma",
        "forma specialis",
        "strain",
        "isolate",
        "serotype",
        "serogroup",
        "biotype",
        "genotype",
        "morph",
        "pathogroup",
    }
)


def is_placeholder_name(name: str) -> bool:
    """True for names such as "environmental samples" or "Homo sp."."""
    return _PLACEHOLDER.search(name) is not None


def is_informal_species_name(name: str) -> bool:
    """True if a species-rank name is not a formal species name: a placeholder,
    an uncertain identification ("cf.", "aff.", "nr."), a cross between species
    ("Populus tremula x Populus alba"), a cultivar group or a strain code."""
    return is_placeholder_name(name) or not _BINOMIAL.fullmatch(_TRAILING_NOTE.sub("", name))


@dataclass(frozen=True, slots=True)
class PruneStats:
    formal_species: int
    informal_kept: int
    dropped: int


def _with_ancestors(seeds: set[int], parents: dict[int, int]) -> set[int]:
    """``seeds`` plus every ancestor of each seed."""
    out: set[int] = set()
    for node in seeds:
        while node not in out:
            out.add(node)
            parent = parents.get(node)
            if parent is None or parent == node:
                break
            node = parent
    return out


def _subtrees(roots: set[int], parents: dict[int, int]) -> set[int]:
    """``roots`` plus every descendant of each root."""
    children: dict[int, list[int]] = defaultdict(list)
    for taxid, parent in parents.items():
        if parent != taxid:
            children[parent].append(taxid)
    out: set[int] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node not in out:
            out.add(node)
            stack.extend(children.get(node, ()))
    return out


def prune_placeholders(
    nodes: dict[int, tuple[int, str]], names: dict[int, str], carrying: set[int]
) -> tuple[dict[int, tuple[int, str]], PruneStats]:
    """Drop placeholder taxa without data and relabel informal species that have data.

    ``nodes`` maps taxid to (parent, rank); ``carrying`` holds the taxids with
    data attached directly. A taxon is dropped, with its whole subtree, when it is
    an informal species or a non-species taxon with a placeholder name, and nothing
    in its subtree carries data or is a formal species. Informal species that stay
    get the rank ``INFORMAL_SPECIES_RANK``. Returns the new nodes and counts.
    """
    parents = {t: p for t, (p, _) in nodes.items()}
    informal: set[int] = set()
    formal: set[int] = set()
    for taxid, (_, rank) in nodes.items():
        if rank == SPECIES_RANK:
            name = names.get(taxid, "")
            (informal if is_informal_species_name(name) else formal).add(taxid)

    needed = _with_ancestors((carrying & parents.keys()) | formal, parents)
    roots = {
        taxid
        for taxid, (_, rank) in nodes.items()
        if taxid not in needed
        and (
            taxid in informal
            or (rank != SPECIES_RANK and is_placeholder_name(names.get(taxid, "")))
        )
    }
    dropped = _subtrees(roots, parents)

    kept = {
        taxid: (parent, INFORMAL_SPECIES_RANK if taxid in informal else rank)
        for taxid, (parent, rank) in nodes.items()
        if taxid not in dropped
    }
    stats = PruneStats(
        formal_species=len(formal),
        informal_kept=len(informal - dropped),
        dropped=len(dropped),
    )
    return kept, stats


def orphans_below_species(nodes: dict[int, tuple[int, str]]) -> list[int]:
    """Taxa with a below-species rank (subspecies, varietas, strain, ...) that have
    no species or informal species above them: NCBI filing errors to report."""
    orphans = []
    for taxid, (parent, rank) in nodes.items():
        if rank not in BELOW_SPECIES_RANKS:
            continue
        node = parent
        while nodes.get(node, (node, ""))[1] not in UNIT_RANKS:
            up = nodes.get(node, (node, ""))[0]
            if up == node:
                orphans.append(taxid)
                break
            node = up
    return orphans
