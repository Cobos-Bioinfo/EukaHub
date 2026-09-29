# Data model

What the numbers in EukaHub mean, where they come from, and how they are stored.
The schema itself is [`infra/postgres/init/001_schema.sql`](../infra/postgres/init/001_schema.sql).

## Scope

- **Taxonomy:** the NCBI Taxonomy (`taxdump`), limited to Eukaryota (taxid 2759)
  plus its two ancestors, `root` (1) and `cellular organisms` (131567), which keep
  lineages complete. About 2.0 million taxa, of which about 1.78 million have rank
  `species`.
- **A clade** is a taxon and everything below it.

## Sources

| Resource (API key) | Source | Unit | Stored as |
|---|---|---|---|
| Assemblies (`ass`) | NCBI Datasets: `datasets summary genome taxon 2759` | One genome assembly. A GenBank assembly and its RefSeq copy count once (the GenBank record is kept), and only the latest version of an assembly is kept. | One row per assembly (`assembly`) |
| Annotations (`ann`) | [Annotrieve](https://genome.crg.es/annotrieve/) `/annotations` | One genome annotation (GFF), with BUSCO completeness and gene counts. | One row per annotation (`annotation`) |
| RNA-Seq (`rna`) | ENA read runs | Sequencing runs on any platform. | Counts per taxon only |
| Long-read RNA-Seq (`lng`) | ENA read runs | Runs on Oxford Nanopore or PacBio SMRT. | Counts per taxon only |

RNA-Seq is kept as counts because there are millions of runs; assemblies and
annotations are small enough (tens of thousands) to keep per record, which is what
powers the record lists and the quality statistics.

## What the dashboard numbers mean

For a clade and a resource:

- **Species** (`n_rows`): taxa of rank `species` in the clade, with or without data.
- **Species with data** (`c_<key>`): species that have at least one record of that
  resource attached directly to the species taxon. **Coverage** is this divided by
  the species count.
- **Total** (`s_<key>`): records attached to the clade's species, summed.
- **Assembly composition**: the clade's assemblies by level (complete genome,
  chromosome, scaffold, contig) and how many are NCBI reference or representative
  genomes.
- **Quality statistics** are computed when requested, over every record in the
  clade: best BUSCO completeness, and the median protein-coding gene count, genome
  size and contig N50. Medians cannot be summed up a tree, so they are not
  precomputed.

Current rules worth knowing (both under discussion, see "Open questions"):

- **Taxa below species** (subspecies, strains, varieties, forms, isolates) have
  their own page with their own counts, but their data is **not** counted toward
  their species or any higher clade. A species whose genomes are all filed under a
  subspecies therefore shows 0% coverage, while its record list and quality
  statistics, which cover the whole subtree, do include those genomes.
- **Placeholder names** (for example "environmental samples", "unclassified ...",
  "... sp.") are NCBI taxa of rank `species` and count as species today. They make
  up a large share of species nodes, which lowers coverage percentages.

Data attached above species rank (a genus or family, which happens for some RNA-Seq
runs) is not counted.

## Tables

| Table | One row per | Notes |
|---|---|---|
| `taxon` | taxon | `taxid`, `name`, `rank`, `parent_id`, and `path`, the lineage from the root as an `ltree` of taxids (`1.131567.2759.33208...`). |
| `clade_features` | taxon with species below it, or a below-species taxon with its own data | The precomputed counts above: `n_rows`, `c_*`, `s_*`, `n_ass_*`, `n_reference`. |
| `assembly` | genome assembly | Level, N50s, genome size, GC, reference category, release date, submitter, BioProjects, NCBI link. |
| `annotation` | genome annotation | Source database, provider, GFF link, gene and protein-coding counts, BUSCO scores. |
| `dataset_meta` | (single row) | When the dataset was built and its row counts; written last, so its presence marks a complete build. |

There are no foreign keys: the data is bulk-loaded and never modified afterwards.

## How queries use it

- **Summary of a clade:** one primary-key lookup in `clade_features`.
- **Breakdown** (the data map and the gaps leaderboard): the clade's descendants at
  a rank, `taxon.path <@ <clade path> AND rank = ...`, joined to `clade_features`.
- **Lineage / breadcrumb:** ancestors via `path @> ...`.
- **Tree of Life:** direct children via `parent_id`.
- **Name search:** trigram index on `taxon.name`.
- **Record lists and quality statistics:** records whose taxon lies in the clade's
  subtree. For per-bucket statistics, each record's ancestors are read from the
  labels of its own `path`.

The breakdown needs no precomputed per-root tables: any taxon can be the root.

## Build and checks

The pipeline (`pipeline/src/eukahub_pipeline/build.py`) parses the taxonomy, trims
it to Eukaryota, fetches the three sources, drops records on unknown taxids, rolls
species-level counts up every lineage with Polars, and loads Postgres. Before a
dataset is published or installed, `validate.check_invariants` requires that:

1. no core table is empty;
2. Eukaryota's species count equals a direct count of `species`-rank taxa under it;
3. no clade has more species with data than species;
4. the assembly-level counts at Eukaryota are positive and do not exceed its total.

## Sizes (full dataset, September 2026)

Database about 2.2 GB on disk: `taxon` 634 MB plus 1.1 GB for its `path` index,
`clade_features` 175 MB. About 68,000 assemblies and 19,000 annotations.

## Open questions

- Should data on subspecies and strains count toward their species?
- How should placeholder "species" be treated: excluded from the species count,
  and reported separately when they carry data?
