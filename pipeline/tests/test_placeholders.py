"""Placeholder names and the pruning of placeholder taxa without data."""

import pytest
from eukahub_core.taxonomy import INFORMAL_SPECIES_RANK
from eukahub_pipeline.placeholders import (
    is_informal_species_name,
    orphans_below_species,
    prune_placeholders,
)


@pytest.mark.parametrize(
    "name",
    [
        "Homo sapiens",
        "[Candida] boidinii",
        "Pseudo-nitzschia multiseries",
        "Mentha x piperita",
        "Mentha × piperita",
        "x Festulolium braunii",
        "Gaussia princeps (in: crustaceans)",
        "Mycena kentingensis (nom. inval.)",
    ],
)
def test_formal_species_names(name: str) -> None:
    assert not is_informal_species_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "Homo sp.",
        "Homo sp. Altai",
        "Homo sapiens environmental sample",
        "uncultured eukaryote",
        "unidentified fungus",
        "Acropora cf. tenuis",
        "Tigriopus aff. angulatus",
        "Euwallacea nr. fornicatus EIL-2018",
        "Populus tremula x Populus alba",
        "Saccharum hybrid cultivar",
        "green alga KS3/2",
        "Echinococcus granulosus sensu lato",
    ],
)
def test_informal_species_names(name: str) -> None:
    assert is_informal_species_name(name)


def _tree() -> tuple[dict[int, tuple[int, str]], dict[int, str]]:
    """Homo with a formal species, two informal ones and an environmental-samples
    container holding one more; a strain sits under one informal species."""
    nodes = {
        1: (1, "no rank"),
        9605: (1, "genus"),
        9606: (9605, "species"),
        10: (9605, "species"),
        11: (9605, "species"),
        12: (11, "strain"),
        20: (9605, "no rank"),
        21: (20, "species"),
    }
    names = {
        1: "root",
        9605: "Homo",
        9606: "Homo sapiens",
        10: "Homo sp.",
        11: "Homo sp. Altai",
        12: "Altai 1",
        20: "environmental samples",
        21: "Homo sapiens environmental sample",
    }
    return nodes, names


def test_prune_drops_placeholders_without_data() -> None:
    nodes, names = _tree()
    kept, stats = prune_placeholders(nodes, names, carrying={12})

    assert set(kept) == {1, 9605, 9606, 11, 12}
    assert kept[11] == (9605, INFORMAL_SPECIES_RANK)  # carries data through its strain
    assert kept[9606] == (9605, "species")
    assert (stats.formal_species, stats.informal_kept, stats.dropped) == (1, 1, 3)


def test_prune_keeps_placeholder_containers_with_formal_species() -> None:
    nodes = {1: (1, "no rank"), 2: (1, "no rank"), 3: (2, "species"), 4: (2, "species")}
    names = {1: "root", 2: "unclassified Homo", 3: "Homo naledi", 4: "Homo sp."}
    kept, _ = prune_placeholders(nodes, names, carrying=set())
    assert set(kept) == {1, 2, 3}


def test_orphans_below_species() -> None:
    nodes = {
        1: (1, "no rank"),
        2: (1, "genus"),
        3: (2, "species"),
        4: (3, "subspecies"),
        5: (2, INFORMAL_SPECIES_RANK),
        6: (5, "strain"),
        7: (2, "varietas"),
    }
    assert orphans_below_species(nodes) == [7]
