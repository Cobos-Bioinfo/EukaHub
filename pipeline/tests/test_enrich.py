"""The build-time columns of the assembly table, on a toy taxonomy."""

import polars as pl
from eukahub_pipeline.enrich import ASSEMBLY_TABLE_COLUMNS, species_of, with_assembly_links
from eukahub_pipeline.fetch_assemblies import ASSEMBLY_COLUMNS

# 1 root -> 9605 genus -> 9606 species -> 63221 subspecies
#                      -> 2813598 informal species -> 99 strain
NODES = {
    1: (1, "no rank"),
    9605: (1, "genus"),
    9606: (9605, "species"),
    63221: (9606, "subspecies"),
    2813598: (9605, "informal species"),
    99: (2813598, "strain"),
}


def _assemblies(rows: list[tuple[str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        [{c: None for c in ASSEMBLY_COLUMNS} | {"assembly_accession": a, "taxid": t} for a, t in rows],
        schema={c: pl.Int64 if c == "taxid" else pl.Utf8 for c in ASSEMBLY_COLUMNS},
    )


def test_a_record_counts_under_its_nearest_species():
    assert species_of({9606, 63221, 2813598, 99, 9605}, NODES) == {
        9606: 9606,
        63221: 9606,
        2813598: 2813598,
        99: 2813598,
        9605: 9605,  # no species above: a unit of its own
    }


def test_annotations_match_any_version_of_the_accession():
    assemblies = _assemblies([("GCA_000001405.29", 9606), ("GCA_000002.1", 63221)])
    annotations = pl.DataFrame(
        {
            "assembly_accession": ["GCF_000001405.40", "GCA_000001405.28", None],
            "busco_complete": [98.5, None, 99.9],
        }
    )
    out = with_assembly_links(assemblies, annotations, NODES)
    assert out.columns == list(ASSEMBLY_TABLE_COLUMNS)
    rows = {r["assembly_accession"]: r for r in out.iter_rows(named=True)}
    assert rows["GCA_000001405.29"]["annotations"] == 2
    assert rows["GCA_000001405.29"]["best_busco"] == 98.5
    assert rows["GCA_000002.1"]["annotations"] == 0
    assert rows["GCA_000002.1"]["best_busco"] is None
    assert rows["GCA_000002.1"]["species_taxid"] == 9606
