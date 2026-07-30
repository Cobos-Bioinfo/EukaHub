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

**Phases 0–1 complete & validated** (2026-07-29). uv workspace (`core`/`api`/
`pipeline`), `web/` Vite placeholder, `infra/docker-compose.yml` (Postgres +
`ltree`). Phase 1 loaded the taxdump into `taxon` (2.9M nodes, `ltree` paths)
and rolled leaf features up into `clade_features` (1.83M clades) with Polars —
no ETE3, no `precomputed_taxa`. Matches Euka-Survey within 0.3%; summary lookup
and worst-case (Eukaryota→phylum) breakdown both run in <1 ms server-side.

**Phase 2 (the API) in progress** (2026-07-30). First endpoint live:
`GET /clade/{taxid}/summary` (the Q1 dashboard payload) — pooled `psycopg`
(`api/…/db.py`), `ltree`-table read (`queries.py`), Pydantic response derived
from `METRICS` (`schemas.py`), tested end-to-end vs the live DB
(`api/tests/test_summary.py`). **Next: `breakdown`**, then `taxon`/lineage,
`export.tsv`, name search — see `docs/roadmap.md`.

Run the build (Postgres up): `uv run --package eukahub-pipeline python -m
eukahub_pipeline.build` (add `--skip-download` to reuse an unpacked taxdump).
Run the API: `uv run --package eukahub-api uvicorn eukahub_api.main:app`.
Tests (whole workspace, DB up): `uv run pytest`.

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
- **Frontend:** React + TypeScript (Vite + React Router SPA).
- **Packaging:** Docker + docker-compose. Python deps via **uv** (workspace).
- **Pipeline:** Python; taxonomy from NCBI taxdump; assemblies via the NCBI
  `datasets` CLI (installed in the dev env); rollup via DuckDB/Polars.

## Non-negotiables (don't reintroduce the old pain)

- **No ETE3** (build or runtime). Taxonomy lives in Postgres.
- **No `precomputed_taxa`-style cache.** The breakdown is one indexed `ltree`
  query for any root.
- **Serving is read-only;** rebuilt offline. Denormalize freely.

## Immediate next step (Phase 2 — the API)

`summary` is done (see Status). Next endpoint: **`breakdown`** —
descendants of a root at a target rank via the `ltree` subtree query, with
filter/sort/limit pushed down into SQL. Reuse Euka-Survey's
`src/database.py` semantics (the `_secondary_sort_key` tiebreaker, the
`FilterLogic` AND/OR enum) — now expressed as one indexed `ltree` predicate
instead of the deleted `precomputed_taxa` cache. Then `taxon`/lineage
breadcrumb, `export.tsv`, name search. Still to wire: generate OpenAPI + TS
types from the `core` metric config for the frontend. See `docs/roadmap.md`
Phase 2.

## Still open

Nothing — all forks resolved. Rollup engine settled on **Polars** at Phase 1
(DuckDB remains a viable alternative). See DECISIONS.md.
