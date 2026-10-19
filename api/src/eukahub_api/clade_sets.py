"""Sets of clades (some included, minus clades inside them excluded) and the
custom groups built from them, checked against the taxonomy.

A set is held as marks, ``{taxid: inside}``: a taxon is in the set when its
nearest marked ancestor (or itself) is marked inside. Marks are kept canonical,
so an outside mark always sits under an inside one and an inside mark under an
outside one or none. A set's counts are then its inside clades' rollup rows
minus its outside clades' rows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from eukahub_core.metrics import COMPOSITION_COLUMNS, COVERAGE_KEYS, TOTAL_KEYS, CladeMetadata
from eukahub_core.taxonomy import INFORMAL_SPECIES_RANK, SPINE_TAXIDS

from eukahub_api.schemas import CustomGroup, TaxonRef

log = logging.getLogger("eukahub.api.clade_sets")

Marks = Mapping[int, bool]

_ADDITIVE_COLUMNS: tuple[str, ...] = ("n_rows",) + COVERAGE_KEYS + TOTAL_KEYS + COMPOSITION_COLUMNS


@dataclass(frozen=True, slots=True)
class SetTaxon:
    """A taxid named in a set of clades, as the dataset has it."""

    taxid: int
    name: str
    rank: str
    path: tuple[int, ...]  # root first, the taxon itself last
    infraspecific: bool
    features: CladeMetadata


@dataclass(frozen=True, slots=True)
class ResolvedGroup:
    group: CustomGroup
    marks: Marks


def _inside(marks: Marks, path: Sequence[int]) -> bool:
    """Whether the taxon at ``path`` is in the region given by ``marks``."""
    for taxid in reversed(path):
        if taxid in marks:
            return marks[taxid]
    return False


def _canonical(marks: Marks, paths: Mapping[int, Sequence[int]]) -> dict[int, bool]:
    """``marks`` without those that repeat their nearest marked ancestor."""
    return {t: v for t, v in marks.items() if v != _inside(marks, paths[t][:-1])}


def _combine(
    regions: Sequence[Marks], op: Callable[..., bool], paths: Mapping[int, Sequence[int]]
) -> dict[int, bool]:
    """The region where ``op`` holds over membership of each of ``regions``. A
    taxon's membership of every region is settled at its nearest mark of any of
    them, so the union of their marks describes the result."""
    positions = set().union(*regions)
    return _canonical({p: op(*(_inside(r, paths[p]) for r in regions)) for p in positions}, paths)


def _taxon_problem(taxid: int, taxa: Mapping[int, SetTaxon]) -> str | None:
    taxon = taxa.get(taxid)
    if taxon is None or taxid in SPINE_TAXIDS:
        return f"taxid {taxid} is not in the dataset"
    if taxon.rank == INFORMAL_SPECIES_RANK or taxon.infraspecific:
        return f"{taxon.name} ({taxid}) is an informal species or below a species"
    return None


def clade_set(
    include: Sequence[int], exclude: Sequence[int], taxa: Mapping[int, SetTaxon]
) -> dict[int, bool] | str:
    """The marks of the clades in ``include`` minus those in ``exclude``, or why
    they don't form a set: a taxid is missing or is not a clade of species, or
    an excluded clade is outside every included one."""
    for taxid in (*include, *exclude):
        if problem := _taxon_problem(taxid, taxa):
            return problem
    included = dict.fromkeys(include, True)
    for taxid in exclude:
        if not _inside(included, taxa[taxid].path):
            return f"{taxa[taxid].name} ({taxid}) is excluded but is not inside an included clade"
    paths = {t: taxon.path for t, taxon in taxa.items()}
    return _canonical({**included, **dict.fromkeys(exclude, False)}, paths)


def set_pieces(marks: Marks, taxa: Mapping[int, SetTaxon]) -> list[tuple[int, list[int]]]:
    """The set as disjoint pieces: each inside clade with the outside clades
    directly under it (canonical marks put each outside mark under one)."""
    pieces: dict[int, list[int]] = {t: [] for t, inside in marks.items() if inside}
    for taxid, inside in marks.items():
        if not inside:
            pieces[next(t for t in reversed(taxa[taxid].path[:-1]) if t in marks)].append(taxid)
    return list(pieces.items())


def _resolve(
    g: CustomGroup,
    parent: Marks | None,
    siblings: Mapping[str, Marks],
    taxa: Mapping[int, SetTaxon],
    paths: Mapping[int, Sequence[int]],
) -> dict[int, bool] | str:
    """The marks of ``g``, or why it does not fit the taxonomy. ``parent`` and
    ``siblings`` are the kept groups it sits under and beside."""
    if g.rest:
        return _combine(
            [parent or {}, *siblings.values()],
            lambda inside_parent, *others: inside_parent and not any(others),
            paths,
        )
    marks = clade_set(g.include, g.exclude, taxa)
    if isinstance(marks, str):
        return marks
    if parent is not None and _combine([marks, parent], lambda own, p: own and not p, paths):
        return f"it is not inside its parent group {g.parent!r}"
    for sid, other in siblings.items():
        if _combine([marks, other], lambda a, b: a and b, paths):
            return f"it overlaps the group {sid!r}"
    return marks


def resolve_groups(
    groups: Sequence[CustomGroup], taxa: Mapping[int, SetTaxon]
) -> list[ResolvedGroup]:
    """The groups that fit the taxonomy, in file order, with their marks.

    A group is skipped (logged) when one of its taxids is missing or is not a
    clade of species, when it excludes a clade outside everything it includes,
    when it is not inside its parent group or overlaps an earlier group under the
    same parent, or when its parent was skipped. A rest group is computed from
    the groups beside it that were kept.
    """
    paths = {t: taxon.path for t, taxon in taxa.items()}
    by_id = {g.id: g for g in groups}

    def depth(g: CustomGroup) -> int:
        return 0 if g.parent is None else 1 + depth(by_id[g.parent])

    resolved: dict[str, dict[int, bool]] = {}
    # Parents before children; under one parent, the rest group after the others.
    for g in sorted(groups, key=lambda g: (depth(g), g.rest)):
        if g.parent is not None and g.parent not in resolved:
            log.warning("skipping custom group %r: its parent %r was skipped", g.id, g.parent)
            continue
        parent = resolved[g.parent] if g.parent is not None else None
        # Top-level groups may overlap; groups under one parent may not.
        siblings = {
            s.id: resolved[s.id]
            for s in groups
            if parent is not None and s.parent == g.parent and not s.rest and s.id in resolved
        }
        result = _resolve(g, parent, siblings, taxa, paths)
        if isinstance(result, str):
            log.warning("skipping custom group %r: %s", g.id, result)
        else:
            resolved[g.id] = result
    return [ResolvedGroup(g, resolved[g.id]) for g in groups if g.id in resolved]


def set_metadata(marks: Marks, taxa: Mapping[int, SetTaxon]) -> CladeMetadata:
    """The set's rollup: inside clades' rows minus outside clades' rows.
    ``taxid`` is 0, since a set is not one taxon."""
    totals = dict.fromkeys(_ADDITIVE_COLUMNS, 0)
    for taxid, inside in marks.items():
        sign = 1 if inside else -1
        for column in _ADDITIVE_COLUMNS:
            totals[column] += sign * getattr(taxa[taxid].features, column)
    return CladeMetadata(taxid=0, **totals)


def taxon_refs(taxids: Iterable[int], taxa: Mapping[int, SetTaxon]) -> list[TaxonRef]:
    return [TaxonRef(taxid=t, name=taxa[t].name, rank=taxa[t].rank) for t in taxids]
