# euka-atlas

> Working name (easy to change). Successor to **Euka-Survey**, rebuilt on a
> production-grade stack. The old Streamlit app stays intact in its own repo;
> this is a clean start.

**What it is:** a web application for exploring how much public genomic data
exists across the tree of life. For any taxon you pick, it answers two
questions:

1. **How much data is there?** Total genome assemblies, functional
   annotations, and RNA-Seq (short- and long-read) for that clade. This is the
   dashboard ("Genomic Resource Summary"), which we are keeping.
2. **How is it distributed below that taxon?** Break the clade down at any
   lower taxonomic rank (phylum, class, order, family, genus, species) and
   explore/compare the sub-groups. Today a table + chart; later, an
   interactive Tree of Life view.

**Data sources** (unchanged from Euka-Survey): NCBI (assemblies), Annotrieve
(annotations), ENA (RNA-Seq runs, split by platform). The dataset is rebuilt
on a schedule offline and served read-only. Nobody writes to this app at
runtime, which shapes almost every architectural decision (see
[`docs/data-model.md`](docs/data-model.md)).

## Status

Planning / greenfield. No application code yet. The current contents are the
design documents:

- [`docs/architecture.md`](docs/architecture.md) — target stack, why, and how
  it maps onto the deployment host (CRG / guigolab).
- [`docs/data-model.md`](docs/data-model.md) — the database decision in depth:
  columnar vs relational, SQL vs graph, and how to store the taxonomy tree.
  **Start here if you only read one.**
- [`docs/roadmap.md`](docs/roadmap.md) — staged migration plan and what we
  reuse from Euka-Survey.
- [`DECISIONS.md`](DECISIONS.md) — lightweight decision log (ADR-style),
  including the choices still open.

## Design north star

- **Drop ETE3 entirely.** The taxonomy moves into our own database, loaded
  from NCBI's taxdump. No PyQt5, no `numpy<2` pin, no spawn-subprocess
  rendering, no cold-start taxonomy build.
- **Kill the redundant `precomputed_taxa` table.** In the old design it was
  86% of the 398 MB database and only worked for six hard-coded root clades.
  A proper taxonomy model answers the same query for *any* root, from a
  single indexed lookup.
- **Keep the good bones of Euka-Survey:** the offline build pipeline, the
  single-source-of-truth metric config, the precomputed clade rollups, and the
  clean domain/presentation split.
