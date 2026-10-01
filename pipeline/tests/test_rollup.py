"""Unit test for the Polars rollup on a toy tree — validates the fan-out and
the per-metric derivations without a database or the real taxdump.
"""

import polars as pl
from eukahub_core.metrics import COMPOSITION_COLUMNS
from eukahub_pipeline.rollup import assemble_leaf_features, carrying_taxids, rollup_from_frames

# Output column order of rollup_from_frames (for the full-row tuple asserts):
# taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng,
# n_ass_complete, n_ass_chromosome, n_ass_scaffold, n_ass_contig, n_reference.
_ZERO_COMPOSITION = (0, 0, 0, 0, 0)  # trailing composition cols when absent from input


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

    assert out[9606] == (9606, 1, 1, 1, 1, 0, 2, 1, 5, 0) + _ZERO_COMPOSITION
    assert out[10090] == (10090, 1, 1, 0, 1, 1, 1, 0, 3, 3) + _ZERO_COMPOSITION
    # Ancestors accumulate both species:
    assert out[2759] == (2759, 2, 2, 1, 2, 1, 3, 1, 8, 3) + _ZERO_COMPOSITION
    assert out[1] == (1, 2, 2, 1, 2, 1, 3, 1, 8, 3) + _ZERO_COMPOSITION
    # A non-species node with no species leaf never appears as a rollup row.
    assert 9605 not in out


def test_rollup_counts_species_without_data() -> None:
    """n_rows counts ALL species in a clade — even those with no features (the
    coverage denominator / 'total species') — while c_*/s_* stay 0 for them.
    The fetched sources cover a small fraction of species, so the roll-up must
    take the species universe from the taxonomy, not from the feature rows.
    """
    taxon = pl.DataFrame(
        {
            "taxid": [1, 2759, 9606, 10090, 7227],
            "rank": ["no rank", "superkingdom", "species", "species", "species"],
            "path": ["1", "1.2759", "1.2759.9606", "1.2759.10090", "1.2759.7227"],
        }
    )
    # Only 9606 carries data; 10090 and 7227 have none.
    features = pl.DataFrame(
        {"taxid": [9606], "short": [5], "long": [0], "ass": [2], "ann": [1]}
    )
    out = {
        r["taxid"]: r for r in rollup_from_frames(taxon, features).iter_rows(named=True)
    }
    # 3 species under the clade, only 1 with assemblies:
    assert out[2759]["n_rows"] == 3
    assert out[2759]["c_ass"] == 1
    assert out[2759]["s_ass"] == 2
    # No-data species still appear as their own rows (n_rows=1, all-zero counts).
    assert out[10090]["n_rows"] == 1
    assert out[10090]["c_ass"] == 0
    assert out[7227]["s_ass"] == 0


def test_rollup_scopes_to_root_subtree() -> None:
    """root_taxid limits the species universe to that subtree — the app is
    Eukaryota-only, but `taxon` holds the whole NCBI tree (all domains)."""
    taxon = pl.DataFrame(
        {
            "taxid": [1, 131567, 2759, 2, 9606, 562],
            "rank": [
                "no rank", "no rank", "superkingdom",
                "superkingdom", "species", "species",
            ],
            "path": [
                "1", "1.131567", "1.131567.2759", "1.131567.2",
                "1.131567.2759.9606", "1.131567.2.562",
            ],
        }
    )
    features = pl.DataFrame(
        {"taxid": [9606], "short": [0], "long": [0], "ass": [1], "ann": [0]}
    )
    out = {
        r["taxid"]: r
        for r in rollup_from_frames(taxon, features, root_taxid=2759).iter_rows(named=True)
    }
    # The eukaryote species is counted; the bacterium (562, E. coli) is excluded.
    assert out[2759]["n_rows"] == 1
    assert 562 not in out  # bacterium never rolled up
    assert 2 not in out  # bacteria superkingdom has no in-scope species
    # Ancestors shared with Eukaryota still appear (root, cellular organisms).
    assert out[1]["n_rows"] == 1
    assert out[131567]["n_rows"] == 1


def test_rollup_composition_columns_sum_up_lineages() -> None:
    """The additive assembly-composition columns roll up the same way as s_*."""
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
            "short": [0, 0],
            "long": [0, 0],
            "ass": [2, 1],
            "ann": [0, 0],
            "n_ass_complete": [1, 0],
            "n_ass_chromosome": [1, 0],
            "n_ass_scaffold": [0, 0],
            "n_ass_contig": [0, 1],
            "n_reference": [1, 0],
        }
    )
    out = {
        r["taxid"]: r
        for r in rollup_from_frames(taxon, features).iter_rows(named=True)
    }
    # Species keep their own composition:
    assert (out[9606]["n_ass_complete"], out[9606]["n_ass_chromosome"]) == (1, 1)
    assert out[10090]["n_ass_contig"] == 1
    # Ancestors sum both species' composition:
    anc = out[2759]
    assert anc["n_ass_complete"] == 1
    assert anc["n_ass_chromosome"] == 1
    assert anc["n_ass_scaffold"] == 0
    assert anc["n_ass_contig"] == 1
    assert anc["n_reference"] == 1
    assert out[1]["n_ass_contig"] == 1  # all the way to the root


def test_rollup_below_species_data_counts_for_the_species() -> None:
    """Data on a subspecies or strain counts toward its species (coverage and
    totals) and every clade above; the finer taxa never add to the species count."""
    taxon = pl.DataFrame(
        {
            "taxid": [1, 2759, 9606, 63221, 2000000, 4641, 4642],
            "rank": ["no rank", "superkingdom", "species", "subspecies", "strain",
                     "species", "varietas"],
            "path": [
                "1",
                "1.2759",
                "1.2759.9606",
                "1.2759.9606.63221",
                "1.2759.9606.63221.2000000",
                "1.2759.4641",
                "1.2759.4641.4642",
            ],
        }
    )
    features = pl.DataFrame(
        {
            "taxid": [9606, 63221, 2000000, 4642],
            "short": [5, 0, 1, 0],
            "long": [0, 0, 0, 0],
            "ass": [2, 3, 1, 4],
            "ann": [1, 0, 0, 0],
        }
    )
    out = {r[0]: r for r in rollup_from_frames(taxon, features).iter_rows()}

    # The species sums its own and its subspecies' and strain's data:
    assert out[9606] == (9606, 1, 1, 1, 1, 0, 6, 1, 6, 0) + _ZERO_COMPOSITION
    # A species with data only on a variety is covered:
    assert out[4641] == (4641, 1, 1, 0, 0, 0, 4, 0, 0, 0) + _ZERO_COMPOSITION
    # Two species, both with assemblies; totals include every record:
    assert out[2759] == (2759, 2, 2, 1, 1, 0, 10, 1, 6, 0) + _ZERO_COMPOSITION
    # Finer taxa are single units holding their own subtree's data:
    assert out[63221] == (63221, 1, 1, 0, 1, 0, 4, 0, 1, 0) + _ZERO_COMPOSITION
    assert out[2000000] == (2000000, 1, 1, 0, 1, 0, 1, 0, 1, 0) + _ZERO_COMPOSITION


def test_rollup_informal_species_and_higher_rank_data() -> None:
    """Data on an informal species or on a genus counts in the totals above it but
    not as species coverage; an informal species is a single unit."""
    taxon = pl.DataFrame(
        {
            "taxid": [1, 2759, 9605, 9606, 2813598],
            "rank": ["no rank", "superkingdom", "genus", "species", "informal species"],
            "path": ["1", "1.2759", "1.2759.9605", "1.2759.9605.9606", "1.2759.9605.2813598"],
        }
    )
    features = pl.DataFrame(
        {
            "taxid": [9605, 2813598],
            "short": [2, 0],
            "long": [0, 0],
            "ass": [0, 3],
            "ann": [0, 0],
        }
    )
    out = {r["taxid"]: r for r in rollup_from_frames(taxon, features).iter_rows(named=True)}

    genus = out[9605]
    assert genus["n_rows"] == 1  # only the formal species
    assert (genus["c_ass"], genus["c_rna"]) == (0, 0)  # it has no data of its own
    assert (genus["s_ass"], genus["s_rna"]) == (3, 2)
    informal = out[2813598]
    assert (informal["n_rows"], informal["c_ass"], informal["s_ass"]) == (1, 1, 3)
    assert out[9606]["s_ass"] == 0


def test_carrying_taxids() -> None:
    features = pl.DataFrame(
        {"taxid": [1, 2, 3], "short": [0, 4, 0], "long": [0, 0, 0], "ass": [0, 0, 1], "ann": [0, 0, 0]}
    )
    assert carrying_taxids(features) == {2, 3}


def test_assemble_leaf_features() -> None:
    """The three fetched sources combine into one per-taxid leaf frame, with
    assembly-level composition + reference count derived from the assemblies."""
    assemblies = pl.DataFrame(
        {
            "taxid": [9606, 9606, 10090],
            "assembly_level": ["Complete Genome", "Chromosome", "Contig"],
            "refseq_category": ["reference genome", None, None],
        }
    )
    annotations = pl.DataFrame({"taxid": [9606]})
    reads = pl.DataFrame({"taxid": [9606], "short": [5], "long": [0]})

    leaf = assemble_leaf_features(assemblies, annotations, reads)
    rows = {r["taxid"]: r for r in leaf.iter_rows(named=True)}

    # every composition column is present and integer-typed
    assert set(COMPOSITION_COLUMNS) <= set(leaf.columns)
    h = rows[9606]
    assert (h["ass"], h["ann"], h["short"], h["long"]) == (2, 1, 5, 0)
    assert (h["n_ass_complete"], h["n_ass_chromosome"], h["n_reference"]) == (1, 1, 1)
    m = rows[10090]
    # taxon present only in assemblies -> other sources fill to 0
    assert (m["ass"], m["ann"], m["short"], m["long"]) == (1, 0, 0, 0)
    assert m["n_ass_contig"] == 1
    assert m["n_reference"] == 0
