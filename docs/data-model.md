# Data model

What the numbers in EukaHub mean, where they come from, and how they are stored.
The schema itself is [`infra/postgres/init/001_schema.sql`](../infra/postgres/init/001_schema.sql).

## Scope

- **Taxonomy:** the NCBI Taxonomy (`taxdump`), limited to Eukaryota (taxid 2759)
  plus its two ancestors, `root` (1) and `cellular organisms` (131567), which keep
  lineages complete, and without placeholder taxa that carry no data (below). About
  980,000 taxa, of which about 773,000 are species.
- **A clade** is a taxon and everything below it.

## Species and placeholder taxa

NCBI gives the rank `species` to about 1.8 million eukaryote taxa, but most of them
are not named species: specimens identified only to genus ("Homo sp."),
environmental and uncultured samples, uncertain identifications ("Acropora cf.
tenuis"), crosses between species ("Populus tremula x Populus alba"), cultivar
groups and strain codes. The build (`pipeline/src/eukahub_pipeline/placeholders.py`)
sorts species-rank taxa by name:

- **Species** have a formal name: a Latin binomial, "Genus epithet", allowing a
  bracketed genus ("[Candida] boidinii"), a hyphenated genus ("Pseudo-nitzschia"), a
  hybrid sign ("Mentha x piperita") and a trailing note such as an author or
  "(nom. inval.)".
- **Informal species** are the rest: names that match Lifemap's placeholder filters
  ("unclassified", "uncultured", "unidentified", "environmental", " sp.") or are not
  a binomial. Those with data anywhere in their subtree are kept with the rank
  `informal species`. Those without data are dropped, with everything below them.
- **Placeholder containers** ("environmental samples", "unclassified Homo") are
  dropped when they hold neither data nor a species.

In the September 2026 taxonomy that leaves 773,445 species and 6,797 informal
species, and drops 1,080,408 taxa. The build also logs any subspecies, variety,
strain or other below-species taxon with no species above it (two in that
taxonomy, both NCBI filing errors); its data still counts toward the clades above it.

## Sources

| Resource (API key) | Source | Unit | Stored as |
|---|---|---|---|
| Assemblies (`ass`) | NCBI Datasets: `datasets summary genome taxon 2759` | One genome assembly. A GenBank assembly and its RefSeq copy count once (the GenBank record is kept), and only the latest version of an assembly is kept. | One row per assembly (`assembly`) |
| Annotations (`ann`) | [Annotrieve](https://genome.crg.es/annotrieve/) `/annotations/report` | One genome annotation (GFF), with BUSCO completeness and gene counts. Includes community-contributed annotations as well as those from GenBank, RefSeq and Ensembl, for example TOGA2 gene projections from the Hiller Lab. | One row per annotation (`annotation`) |
| RNA-Seq (`rna`) | ENA read runs | Sequencing runs on any platform. | Counts per taxon only |
| Long-read RNA-Seq (`lng`) | ENA read runs | Runs on Oxford Nanopore or PacBio SMRT. | Counts per taxon only |

RNA-Seq is kept as counts because there are millions of runs; assemblies and
annotations are small enough (tens of thousands) to keep per record, which is what
powers the record lists and the quality statistics.

## What the dashboard numbers mean

For a clade and a resource:

- **Species** (`n_rows`): taxa of rank `species` in the clade, with or without data.
  Informal species and below-species taxa are not counted.
- **Species with data** (`c_<key>`): species with at least one record of that
  resource, attached to the species itself or to a taxon below it (a subspecies,
  variety or strain). **Coverage** is this divided by the species count.
- **Total** (`s_<key>`): every record in the clade, whatever taxon it is attached
  to: a species, a subspecies, an informal species, or a higher rank such as a genus
  (some RNA-Seq runs). It equals the length of the clade's record list.
- **Assembly composition**: the clade's assemblies by level (complete genome,
  chromosome, scaffold, contig) and how many are NCBI reference or representative
  genomes.
- **Quality statistics**, over every record in the clade: best BUSCO completeness,
  and the median protein-coding gene count, genome size and contig N50. Medians
  cannot be summed up a tree, so the build computes each clade's from its own
  records, counting every record for each of its ancestors. Those of a set of
  clades (include minus exclude) are computed when requested, from the records in
  the set.

A species, an informal species or a below-species taxon is a single unit: its row
has `n_rows = 1`, and `c_<key> = 1` when it has that resource. Its page lists the
taxa below it and splits each total into the records attached to the taxon itself
and those on finer taxa (`direct` in the summary API).

## Tables

| Table | One row per | Notes |
|---|---|---|
| `taxon` | taxon | `taxid`, `name`, `rank` (NCBI's, or `informal species`), `parent_id`, and `path`, the lineage from the root as an `ltree` of taxids (`1.131567.2759.33208...`). |
| `clade_features` | taxon with species or data below it | The precomputed counts above: `n_rows`, `c_*`, `s_*`, `n_ass_*`, `n_reference`. |
| `clade_stats` | taxon with records below it | The quality statistics above: `busco`, `genes`, `genome_size`, `contig_n50`; null when none of its records has the value. |
| `assembly` | genome assembly | Level, N50s, genome size, GC, reference category, release date, submitter, BioProjects, NCBI link. |
| `annotation` | genome annotation | Source database, provider, GFF link, gene and protein-coding counts, BUSCO scores. |
| `dataset_meta` | (single row) | When the dataset was built and its row counts; written last, so its presence marks a complete build. |

One foreign key: `clade_features.taxid` references `taxon`, which is why `taxon` keeps the
root and "cellular organisms". The record tables have none: their taxids and accessions
come from independent sources, and the build drops what doesn't match instead of failing
(see `infra/postgres/init/001_schema.sql`).

## How queries use it

- **Summary of a clade:** one primary-key lookup in `clade_features`, and one in
  `clade_stats` for its quality statistics.
- **Breakdown** (the data map and the gaps leaderboard): the clade's descendants at
  a rank, `taxon.path <@ <clade path> AND rank = ...`, joined to `clade_features`.
- **Lineage / breadcrumb:** ancestors via `path @> ...`.
- **Tree of Life:** direct children via `parent_id`.
- **Name search:** trigram index on `taxon.name`.
- **Record lists:** records whose taxon lies in the clade's subtree.
- **Quality statistics of a set of clades:** the records in the set, one subtree
  filter per included clade.

The breakdown needs no precomputed per-root tables: any taxon can be the root.

## Build and checks

The pipeline (`pipeline/src/eukahub_pipeline/build.py`) parses the taxonomy, trims
it to Eukaryota, fetches the three sources, drops records on unknown taxids, drops
placeholder taxa without data, rolls the counts up every lineage with Polars,
computes each clade's quality statistics from its records the same way (each
record's ancestors are the labels of its taxon's `path`), and loads Postgres. Before a dataset is published or installed,
`validate.check_invariants` requires that:

1. no core table is empty, and Eukaryota has a taxon and a rollup row;
2. Eukaryota's species count equals a direct count of `species`-rank taxa under it;
3. Eukaryota's assembly and annotation totals equal the rows in those tables;
4. every informal species carries data;
5. no clade has more species with data than species;
6. the assembly-level counts at Eukaryota are positive and do not exceed its total;
7. every resource has data for at least one species;
8. no two assembly rows share an assembly number;
9. the fields the statistics and composition read are filled on most records
   (assembly level, contig N50 and genome size on 90% of assemblies, protein-coding
   genes on 90% and BUSCO on 50% of annotations), so a field a source renames fails
   the build instead of shipping empty;
10. `clade_stats` has a row for exactly the clades with records below them;
11. the stored statistics of a few large clades (Eukaryota, Metazoa, Mammalia,
    Primates, Fungi, plants) equal Postgres' own median and maximum over their
    records.

A partial download that is consistent with itself passes all of these, so the
rebuild also compares the build's key counts (taxa, species, and per resource the
species with data and the records) with the previous Release's, published with it
as `dataset-counts.json`, and fails when one fell by more than 10%. A drop that is
real can be published by running the rebuild by hand with "Publish even if counts
fell sharply" ticked.

`taxon` is loaded sorted by path, so each subtree's rows sit together on disk and
a subtree query reads only its own pages.

## Sizes (full dataset, September 2026)

Database about 950 MB on disk: `taxon` 290 MB plus 410 MB for its `path` index,
`clade_features` 107 MB, `clade_stats` 4 MB (about 52,600 clades). About 70,500 assemblies and 19,500 annotations. The
published dump is about 30 MB.
