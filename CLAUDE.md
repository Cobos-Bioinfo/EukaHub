# CLAUDE.md — euka-atlas

Read this first, then the docs below. This file is the resume anchor for a
fresh session.

## What this is

A production-grade rewrite of **Euka-Survey** (a Streamlit app that explores
public genomic-data availability across the tree of life). The old app lives,
intact, at `../Euka-Survey` (sibling directory) — read it when porting logic.

The app answers two questions for any user-picked taxon:
1. **How much data is there?** (dashboard / "Genomic Resource Summary")
2. **How is it distributed at a lower taxonomic rank?** (breakdown: table/chart
   now, interactive Tree of Life later)

Data sources (unchanged): NCBI (assemblies), Annotrieve (annotations), ENA
(RNA-Seq). Dataset is rebuilt offline on a schedule and served **read-only** —
this single fact drives most of the design.

## Status

Greenfield. Planning is done; the stack is decided; **no application code
exists yet.** The next work is Phase 0 + Phase 1 in `docs/roadmap.md`.

## Read these before doing anything

- `README.md` — overview + status.
- `DECISIONS.md` — every settled decision (ADR-style) and the few still open.
- `docs/data-model.md` — **the core doc.** The database design and the
  reasoning (columnar vs relational, SQL vs graph, tree storage).
- `docs/architecture.md` — target stack + how it maps onto the deploy host.
- `docs/roadmap.md` — the staged plan.

## Settled stack (see DECISIONS.md for the why)

- **DB:** PostgreSQL. Taxonomy = `parent_id` (adjacency) + `ltree` lineage.
  Feature rollups kept from Euka-Survey. **No ETE3. No `precomputed_taxa`.**
- **Backend:** FastAPI (Python), REST + auto-OpenAPI. Reuse the old domain
  logic + build pipeline.
- **Frontend:** React + TypeScript.
- **Packaging:** Docker + docker-compose.
- **Pipeline:** Python; taxonomy from NCBI taxdump; rollup via DuckDB/Polars.

## Non-negotiables (do not reintroduce the old pain)

- Drop **ETE3** entirely (build-time and runtime). Taxonomy lives in Postgres.
- No `precomputed_taxa`-style denormalized cache. The breakdown is one indexed
  `ltree` query for **any** root.
- Serving is **read-only**; the dataset is rebuilt offline. Denormalize freely.

## Immediate next step

Phase 1 (data foundation) + the Phase 0 scaffold it needs:
1. Repo layout (`pipeline/`, `api/`, `web/`, `infra/`) + `docker-compose.yml`
   with Postgres.
2. Load NCBI taxdump into `taxon` (`taxid, name, rank, parent_id, path`).
3. Port the rollup into `clade_features`; validate against Euka-Survey numbers
   (e.g. Eukaryota taxid 2759).
4. Prove both questions answer fast with no ETE3 and no `precomputed_taxa`.

## Still open (decide at scaffold time)

Next.js vs Vite · `ltree` vs integer-array ancestors · DuckDB vs Polars.
