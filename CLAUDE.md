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

**Phase 2 (the API) — all five read endpoints done** (2026-07-30):
`summary` (Q1), `breakdown` (Q2 — descendants at a rank via one `ltree`
subtree query, filter/sort/limit pushed into SQL, `COUNT(*) OVER ()` for the
pre-limit total), `export.tsv` (full breakdown streamed via a server-side
cursor; old public TSV schema), `taxon/{taxid}` (root→node lineage via
`path @>` + `nlevel`), and `search` (name search, `pg_trgm` GIN index on
`taxon.name` — added to the schema and the live DB). Structure: pooled
`psycopg` (`api/…/db.py`), SQL in `queries.py`, Pydantic responses +
query-param enums both derived from `METRICS`. Breakdown defaults mirror
Euka-Survey (sort `n_rows`, exclude-empty, AND, top 25; ranks =
ALLOWED_RANKS). 35 end-to-end tests vs the live DB (shared `client` fixture
in `api/tests/conftest.py`). **Next: generate OpenAPI + TS types from the
metric config, then Phase 3 (the dashboard frontend)** — see `docs/roadmap.md`.

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

## Immediate next step (finish Phase 2 → start Phase 3)

All five read endpoints are done and tested (see Status). Two things remain
before the frontend:

1. **OpenAPI → TS types.** Generate the TypeScript client/types from the
   API's OpenAPI schema so the React app can't drift from the metric config
   (`METRICS` already drives the responses + query-param enums). Wire it as a
   `web/` build step.
2. **Phase 3 — the dashboard.** Rebuild the "Genomic Resource Summary": metric
   cards (from `/metrics-config` + `/clade/{taxid}/summary`), total-species,
   coverage bars, lineage breadcrumb (`/taxon/{taxid}`), root picker
   (`/search`). See `docs/roadmap.md` Phase 3.

Consider response caching for the common clades (Eukaryota, Metazoa, …) — the
data is read-only between rebuilds, so it's cache-friendly.

## Still open

Nothing — all forks resolved. Rollup engine settled on **Polars** at Phase 1
(DuckDB remains a viable alternative). See DECISIONS.md.
