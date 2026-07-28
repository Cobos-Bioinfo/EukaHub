# EukaHub

Successor to **Euka-Survey**, rebuilt on a production-grade stack. The old
Streamlit app stays intact in its own repo; this is a clean start.

A web app for exploring how much public genomic data exists across the tree of
life. For any taxon it answers two questions:

1. **How much data is there?** Genome assemblies, functional annotations, and
   RNA-Seq (short/long-read) for the clade — the "Genomic Resource Summary"
   dashboard.
2. **How is it distributed below that taxon?** Break the clade down at any lower
   rank (phylum … species) and compare sub-groups. A table + chart now; an
   interactive Tree of Life later.

**Data sources** (unchanged): NCBI (assemblies), Annotrieve (annotations), ENA
(RNA-Seq). The dataset is rebuilt offline on a schedule and served read-only —
this single fact drives most design decisions.

## Status

Planning / greenfield. No application code yet — only design docs:

- [`docs/data-model.md`](docs/data-model.md) — the core doc: database design and
  taxonomy-tree storage. **Start here.**
- [`docs/architecture.md`](docs/architecture.md) — target stack and deploy host.
- [`docs/roadmap.md`](docs/roadmap.md) — staged plan and what we reuse.
- [`DECISIONS.md`](DECISIONS.md) — settled decisions and the few still open.
