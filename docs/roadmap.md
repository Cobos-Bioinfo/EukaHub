# Migration roadmap

Staged so there is a working, demoable thing at the end of each phase. The two
open forks (DB engine, frontend framework) only need locking before the phases
that depend on them.

## Phase 0 — Decide & scaffold
- Resolve the open forks in [`../DECISIONS.md`](../DECISIONS.md).
- Monorepo layout: `pipeline/`, `api/`, `web/`, `infra/` (docker-compose), `docs/`.
- `docker-compose.yml` with Postgres + a placeholder API + web.

## Phase 1 — Data foundation (the real work)
- Load NCBI **taxdump** into `taxon`: `taxid, name, rank, parent_id, path`.
  Verify counts against the old DB (~1.8M eukaryote nodes).
- Port the **rollup** into `clade_features` (reuse Euka-Survey's logic; move the
  aggregation to DuckDB/Polars). Validate against the old numbers for known
  clades (e.g. Eukaryota 2759).
- Confirm both canonical queries run fast **without** `precomputed_taxa` and
  **without** ETE3. This proves the thesis of the redesign.

## Phase 2 — API
- FastAPI endpoints: `summary`, `breakdown` (filter/sort/limit pushed down),
  `taxon`/lineage (breadcrumb), `export.tsv`, name search.
- Port the `Metric` config as single source of truth; generate OpenAPI + TS types
  from it. Response caching for common clades.

## Phase 3 — Frontend: the dashboard (Q1)
- Rebuild the "Genomic Resource Summary": metric cards, total-species, coverage
  bars, Wikipedia "About" card, lineage breadcrumb, root picker.

## Phase 4 — Frontend: the breakdown (Q2)
- The filter/sort/limit **table** with coverage bars, plus a bar chart.
- Downloads (displayed rows + full breakdown TSV).

## Phase 5 — Productionization
- Dockerized deploy, health checks, structured logging, scheduled rebuild (GitHub
  Actions or Nextflow), staging vs prod DB, basic metrics.

## Phase 6 — Stretch: interactive Tree of Life
- WebGL/canvas hierarchical view with lazy-expand (`parent_id`) and subtree fetch
  (materialized lineage). The ambitious showcase piece.

## Reuse vs rebuild vs delete

| Reuse (port) | Rebuild | Delete |
|---|---|---|
| Build pipeline (Python) | Presentation (Streamlit → SPA) | ETE3 (build + runtime) |
| Rollup/aggregation logic | Data-access as an HTTP API | PyQt5 / matplotlib tree |
| `Metric` config | Taxonomy storage (into our DB) | `precomputed_taxa` + index |
| filter/sort/limit semantics | | 400 MB download model |
| Schema-version discipline | | |
| Wikipedia "About" card idea | | |
