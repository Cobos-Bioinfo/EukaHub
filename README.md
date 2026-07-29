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

**Phase 0 scaffold in place**; Phase 1 (loading the real dataset) is the active
work. Design docs:

- [`docs/data-model.md`](docs/data-model.md) — the core doc: database design and
  taxonomy-tree storage. **Start here.**
- [`docs/architecture.md`](docs/architecture.md) — target stack and deploy host.
- [`docs/roadmap.md`](docs/roadmap.md) — staged plan and what we reuse.
- [`DECISIONS.md`](DECISIONS.md) — settled decisions and the few still open.

## Repository layout

```
core/      shared domain model — the metric config (single source of truth)
api/       FastAPI service (placeholder; real endpoints in Phase 2)
pipeline/  offline build: NCBI taxdump loader + clade-feature roll-up
web/       React + TypeScript SPA (Vite; placeholder until Phases 3–4)
infra/     docker-compose.yml + Postgres init schema (taxon + clade_features)
docs/      design docs
```

Python is a **uv workspace** (`core` / `api` / `pipeline`); the frontend is a
Vite SPA.

## Development

```bash
# Python workspace (installs core + api + pipeline and dev tools)
uv sync

# Run the pipeline's unit tests (taxdump parser + ltree path builder)
uv run pytest pipeline

# Bring up Postgres (with ltree) + placeholder API + web
docker compose -f infra/docker-compose.yml up --build
# API:  http://localhost:8000/health   ·   http://localhost:8000/docs
# Web:  http://localhost:5173
```
