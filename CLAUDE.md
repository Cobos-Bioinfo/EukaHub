# CLAUDE.md — EukaHub

Resume anchor for a fresh session. Read this, then the docs below.

## What this is

A production-grade rewrite of **Euka-Survey** (a Streamlit app exploring public
genomic-data availability across the tree of life). The old app lives intact at
`../Euka-Survey` (sibling dir) — read it when porting logic.

For any user-picked taxon the app answers two questions:
1. **How much data is there?** (the "Genomic Resource Summary" dashboard)
2. **How is it distributed at a lower rank?** (breakdown: table/chart now,
   interactive Tree of Life later)

Data sources: NCBI (assemblies), Annotrieve (annotations), ENA (RNA-Seq). The
dataset is rebuilt offline on a schedule and served **read-only** — this drives
most of the design.

## Status

Greenfield. Planning done, stack decided, **no application code yet.** Next work
is Phase 0 + Phase 1 in `docs/roadmap.md`.

## Read before doing anything

- `docs/data-model.md` — **the core doc.** DB design + taxonomy-tree storage.
- `docs/architecture.md` — target stack and how it maps to the deploy host.
- `docs/roadmap.md` — the staged plan.
- `DECISIONS.md` — every settled decision and the few still open.
- `README.md` — overview + status.

## Settled stack (why in DECISIONS.md)

- **DB:** PostgreSQL. Taxonomy = `parent_id` (adjacency) + `ltree` lineage.
  Feature rollups kept from Euka-Survey.
- **Backend:** FastAPI (Python), REST + auto-OpenAPI. Reuse old domain logic.
- **Frontend:** React + TypeScript.
- **Packaging:** Docker + docker-compose.
- **Pipeline:** Python; taxonomy from NCBI taxdump; rollup via DuckDB/Polars.

## Non-negotiables (don't reintroduce the old pain)

- **No ETE3** (build or runtime). Taxonomy lives in Postgres.
- **No `precomputed_taxa`-style cache.** The breakdown is one indexed `ltree`
  query for any root.
- **Serving is read-only;** rebuilt offline. Denormalize freely.

## Immediate next step (Phase 1 + the Phase 0 scaffold it needs)

1. Repo layout (`pipeline/`, `api/`, `web/`, `infra/`) + `docker-compose.yml`
   with Postgres.
2. Load NCBI taxdump into `taxon` (`taxid, name, rank, parent_id, path`).
3. Port the rollup into `clade_features`; validate against Euka-Survey numbers
   (e.g. Eukaryota taxid 2759).
4. Prove both questions answer fast with no ETE3 and no `precomputed_taxa`.

## Still open (decide at scaffold time)

Next.js vs Vite · `ltree` vs integer-array ancestors · DuckDB vs Polars.
